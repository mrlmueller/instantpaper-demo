"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Cookies from "js-cookie";
import {
  Timestamp,
  addDoc,
  deleteDoc,
  doc,
  limit,
  onSnapshot,
  orderBy,
  query,
  where,
} from "firebase/firestore";
import { deleteObject, getStorage, ref as storageRef, uploadBytes } from "firebase/storage";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  BarChart3,
  Check,
  ExternalLink,
  FileText,
  FileUp,
  Loader2,
  Play,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";

import type { Kapitel } from "@/app/actions/kapitels";
import { useAuth } from "@/app/components/providers/AuthProvider";
import { ViewportWarning } from "@/app/components/viewport-warning";
import { PdfExtractDialog, type PdfExtractRequest } from "@/app/components/quellen-finder/PdfExtractDialog";
import { firebaseApp } from "@/app/lib/firebase/config";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { getDownloadUrlFromStorage } from "@/app/lib/firebase/storage";
import {
  projectPdfsCol,
  projectResearchRunsCol,
  quellenFinderPdfScanDocsCol,
  quellenFinderPdfScanSectionsCol,
} from "@/app/lib/firestore/refs";
import type {
  PdfScanDocSummaryDoc,
  PdfScanResultDoc,
  ProjectPdfDoc,
  QuellenFinderRunDoc,
} from "@/app/lib/firestore/types";

import { PdfScanDetailsDialog } from "./PdfScanDetailsDialog";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type WithId<T> = T & { id: string };
type PdfRow = WithId<ProjectPdfDoc>;
type RunRow = WithId<QuellenFinderRunDoc>;
type PdfDocRow = WithId<PdfScanDocSummaryDoc>;
type PdfSectionRow = WithId<PdfScanResultDoc>;
type ToDateLike = { toDate: () => Date };
export type PdfScanWorkspacePreview = {
  pdfs: PdfRow[];
  runs: RunRow[];
  docRows: PdfDocRow[];
  sectionsByDocId: Record<string, PdfSectionRow[]>;
  initialSelectedKapitelId?: string | null;
  initialActiveRunId?: string | null;
  initialActiveDocId?: string | null;
};

const PDF_SCAN_PIPELINE_STEPS: Array<{ key: string; label: string }> = [
  { key: "prepare_inputs", label: "Inputs" },
  { key: "download_pdfs", label: "Download" },
  { key: "phase_a", label: "Phase A" },
  { key: "phase_b", label: "Phase B" },
  { key: "phase_c", label: "Phase C" },
  { key: "phase_d", label: "Phase D" },
  { key: "phase_e", label: "Phase E" },
  { key: "phase_f", label: "Phase F" },
  { key: "phase_g", label: "Phase G" },
  { key: "persist_results", label: "Persist" },
];

function hasToDate(value: unknown): value is ToDateLike {
  if (typeof value !== "object" || value === null) return false;
  const rec = value as Record<string, unknown>;
  return typeof rec.toDate === "function";
}

function toDateOrNull(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (!hasToDate(value)) return null;
  try {
    const date = value.toDate();
    return date instanceof Date ? date : null;
  } catch {
    return null;
  }
}

function formatIntDe(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("de-DE");
}

function formatScore(value: unknown, digits = 1): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

function formatProbability(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(3);
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
  const totalSeconds = Math.max(0, Math.floor(Number(ms) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatElapsedShort(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(Number(ms) / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  return formatDurationMs(ms);
}

function formatBytes(bytes: unknown): string {
  const n = typeof bytes === "number" && Number.isFinite(bytes) ? bytes : Number(bytes || 0);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n < 1024) return `${Math.round(n)} B`;
  const kb = n / 1024;
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

function formatPageRange(pageStart: unknown, pageEnd: unknown): string {
  const start = typeof pageStart === "number" ? pageStart : Number(pageStart);
  const end = typeof pageEnd === "number" ? pageEnd : Number(pageEnd);
  if (!Number.isFinite(start) && !Number.isFinite(end)) return "—";
  if (!Number.isFinite(start)) return `bis S. ${Math.round(end)}`;
  if (!Number.isFinite(end) || Math.round(start) === Math.round(end)) return `S. ${Math.round(start)}`;
  return `S. ${Math.round(start)}-${Math.round(end)}`;
}

function stageLabel(run: RunRow | null): string {
  if (!run) return "";
  const message = String(run.progress?.message || "").trim();
  const stage = String(run.progress?.stage || "").trim();
  const current = run.progress?.current;
  const total = run.progress?.total;
  const counts =
    typeof current === "number" && typeof total === "number" && total > 0 ? ` (${formatIntDe(current)}/${formatIntDe(total)})` : "";
  if (message) return `${message}${counts}`;
  if (stage) return `${stage}${counts}`;
  return "—";
}

function readTopScore(row: PdfDocRow): number {
  return typeof row.topSectionScore === "number" && Number.isFinite(row.topSectionScore) ? row.topSectionScore : -1;
}

function scoreToneClasses(score: number | null): string {
  if (typeof score !== "number" || !Number.isFinite(score)) return "border-border bg-muted/40 text-muted-foreground";
  if (score >= 70) return "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/20 dark:text-emerald-200";
  if (score >= 35) return "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/20 dark:text-amber-200";
  return "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/20 dark:text-rose-200";
}

function statusBadgeVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "success") return "default";
  if (status === "running") return "secondary";
  if (status === "error") return "destructive";
  return "outline";
}

async function readFastApiError(res: Response): Promise<string> {
  try {
    const payload = (await res.json().catch(() => ({}))) as { detail?: unknown; error?: unknown; message?: unknown };
    for (const candidate of [payload.detail, payload.error, payload.message]) {
      if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    }
  } catch {
    // ignore
  }
  return "Request failed.";
}

const StatusPill = memo(function StatusPill({ status }: { status: string }) {
  const normalized = String(status || "").trim();
  const label =
    normalized === "queued"
      ? "Queued"
      : normalized === "running"
        ? "Running"
        : normalized === "success"
          ? "Success"
          : normalized === "cancelled"
            ? "Cancelled"
            : normalized === "error"
              ? "Error"
              : normalized || "—";

  return (
    <Badge variant={statusBadgeVariant(normalized)} className="tabular-nums">
      {label}
    </Badge>
  );
});

const SidebarEmptyState = memo(function SidebarEmptyState({ label }: { label: string }) {
  return <div className="px-5 py-6 text-xs text-sidebar-foreground/70">{label}</div>;
});

const MainEmptyState = memo(function MainEmptyState({ selectedKapitel }: { selectedKapitel: Kapitel | null }) {
  return (
    <div className="flex min-h-[480px] items-center justify-center px-8">
      <div className="max-w-[620px] text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-border bg-background/80 shadow-sm">
          <FileText className="h-8 w-8 text-muted-foreground/60" />
        </div>
        <div className="mt-6 text-[38px] font-semibold tracking-[-0.02em] text-foreground/90">PDF-Scan starten</div>
        <div className="mt-4 text-lg leading-8 text-muted-foreground">
          {selectedKapitel
            ? "Wähle links die PDFs aus und starte den Scan. Die neue Pipeline läuft deutlich länger und meldet ihren Fortschritt live zurück."
            : "Wähle links ein Kapitel, lade PDFs hoch und starte dann den Scan."}
        </div>
      </div>
    </div>
  );
});

function ResultSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 3 }).map((_, idx) => (
        <Card key={idx} className="p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
              <div className="flex flex-wrap gap-2 pt-2">
                <Skeleton className="h-6 w-24 rounded-full" />
                <Skeleton className="h-6 w-20 rounded-full" />
                <Skeleton className="h-6 w-28 rounded-full" />
              </div>
            </div>
            <div className="space-y-2">
              <Skeleton className="h-8 w-16 rounded-md" />
              <Skeleton className="h-6 w-24 rounded-full" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

export function PdfScanWorkspace({
  initialKapitels,
  projektId,
  projektName,
  preview,
}: {
  initialKapitels: Kapitel[];
  projektId: string;
  projektName: string;
  preview?: PdfScanWorkspacePreview;
}) {
  const { user } = useAuth();
  const previewMode = Boolean(preview);

  const kapitels = useMemo(() => initialKapitels ?? [], [initialKapitels]);
  const [selectedKapitelId, setSelectedKapitelId] = useState<string | null>(() => preview?.initialSelectedKapitelId ?? null);

  const [pdfs, setPdfs] = useState<PdfRow[]>(() => preview?.pdfs ?? []);
  const [selectedPdfIds, setSelectedPdfIds] = useState<string[]>(() => (preview?.pdfs ?? []).map((pdf) => pdf.id));
  const [pdfLibraryFilter, setPdfLibraryFilter] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [deletingPdfId, setDeletingPdfId] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunRow[]>(() => preview?.runs ?? []);
  const [activeRunId, setActiveRunId] = useState<string | null>(() => preview?.initialActiveRunId ?? null);

  const [docRows, setDocRows] = useState<PdfDocRow[]>(() => preview?.docRows ?? []);
  const [docRowsLoaded, setDocRowsLoaded] = useState(() => previewMode);
  const [activeDocId, setActiveDocId] = useState<string | null>(() => preview?.initialActiveDocId ?? null);

  const [sectionRows, setSectionRows] = useState<PdfSectionRow[]>(() => {
    const initialDocId = preview?.initialActiveDocId ?? null;
    return initialDocId ? (preview?.sectionsByDocId?.[initialDocId] ?? []) : [];
  });
  const [sectionRowsLoaded, setSectionRowsLoaded] = useState(() => previewMode);

  const [resultFilter, setResultFilter] = useState("");
  const [extractOpen, setExtractOpen] = useState(false);
  const [extractRequest, setExtractRequest] = useState<PdfExtractRequest | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsDoc, setDetailsDoc] = useState<PdfDocRow | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const lastRunStatus = useRef<{ runId: string; status: string } | null>(null);
  const previousActiveRunIdRef = useRef<string | null>(null);

  const selectedKapitel = useMemo(() => {
    if (!selectedKapitelId) return null;
    return kapitels.find((item) => item.id === selectedKapitelId) ?? null;
  }, [kapitels, selectedKapitelId]);

  const pdfsById = useMemo(() => {
    const map = new Map<string, PdfRow>();
    for (const pdf of pdfs) map.set(pdf.id, pdf);
    return map;
  }, [pdfs]);

  const pdfScanRuns = useMemo(() => runs.filter((run) => run.kind === "pdf_scan"), [runs]);

  const activeRun = useMemo(() => {
    if (activeRunId) {
      const found = pdfScanRuns.find((run) => run.id === activeRunId);
      if (found) return found;
    }
    if (selectedKapitelId) {
      return pdfScanRuns.find((run) => Array.isArray(run.kapitelIds) && run.kapitelIds.includes(selectedKapitelId)) ?? null;
    }
    return pdfScanRuns[0] ?? null;
  }, [activeRunId, pdfScanRuns, selectedKapitelId]);

  const selectedPdfIdSet = useMemo(() => new Set(selectedPdfIds), [selectedPdfIds]);

  const selectedPdfBytes = useMemo(
    () =>
      pdfs.reduce((sum, pdf) => {
        if (!selectedPdfIdSet.has(pdf.id)) return sum;
        return sum + (typeof pdf.size === "number" && Number.isFinite(pdf.size) ? pdf.size : 0);
      }, 0),
    [pdfs, selectedPdfIdSet]
  );

  const filteredPdfs = useMemo(() => {
    const q = pdfLibraryFilter.trim().toLowerCase();
    const rows = q
      ? pdfs.filter((pdf) => String(pdf.filename || "").toLowerCase().includes(q))
      : [...pdfs];

    rows.sort((a, b) => {
      const selectedDiff = Number(selectedPdfIdSet.has(b.id)) - Number(selectedPdfIdSet.has(a.id));
      if (selectedDiff !== 0) return selectedDiff;
      return String(a.filename || "").localeCompare(String(b.filename || ""), "de");
    });

    return rows;
  }, [pdfLibraryFilter, pdfs, selectedPdfIdSet]);

  const selectedVisibleCount = useMemo(
    () => filteredPdfs.reduce((sum, pdf) => sum + (selectedPdfIdSet.has(pdf.id) ? 1 : 0), 0),
    [filteredPdfs, selectedPdfIdSet]
  );

  const projectRunningRun = useMemo(
    () => pdfScanRuns.find((run) => run.status === "queued" || run.status === "running") ?? null,
    [pdfScanRuns]
  );

  useEffect(() => {
    if (selectedKapitelId) return;
    if (activeRun?.kapitelIds?.[0]) {
      setSelectedKapitelId(activeRun.kapitelIds[0]);
      return;
    }
    if (kapitels.length) setSelectedKapitelId(kapitels[0]?.id ?? null);
  }, [activeRun?.kapitelIds, kapitels, selectedKapitelId]);

  useEffect(() => {
    setSelectedPdfIds((prev) => prev.filter((id) => pdfsById.has(id)));
  }, [pdfsById]);

  useEffect(() => {
    if (!activeRunId) return;
    if (pdfScanRuns.some((run) => run.id === activeRunId)) return;
    setActiveRunId(null);
  }, [activeRunId, pdfScanRuns]);

  useEffect(() => {
    const nextRunId = activeRun?.id ?? null;
    if (previousActiveRunIdRef.current === null) {
      previousActiveRunIdRef.current = nextRunId;
      return;
    }
    if (previousActiveRunIdRef.current === nextRunId) return;
    previousActiveRunIdRef.current = nextRunId;

    setActiveDocId(null);
    setSectionRows([]);
    setSectionRowsLoaded(previewMode);
    setDetailsDoc(null);
    setDetailsOpen(false);
    setExtractOpen(false);
    setExtractRequest(null);
  }, [activeRun?.id, previewMode]);

  useEffect(() => {
    if (previewMode) return;
    if (!user?.uid || !projektId) return;
    const q = query(projectPdfsCol(firestoreClient, user.uid, projektId), orderBy("createdAt", "desc"), limit(200));
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((entry) => ({ id: entry.id, ...(entry.data() as ProjectPdfDoc) }));
        setPdfs(next);
      },
      (err) => {
        console.error("Failed to load project pdfs:", err);
        setPdfs([]);
      }
    );
  }, [previewMode, projektId, user?.uid]);

  useEffect(() => {
    if (previewMode) return;
    if (!user?.uid || !projektId) return;
    const q = query(
      projectResearchRunsCol(firestoreClient, user.uid, projektId),
      where("kind", "==", "pdf_scan"),
      limit(50)
    );
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs
          .map((entry) => ({ id: entry.id, ...(entry.data() as QuellenFinderRunDoc) }))
          .sort((a, b) => (toDateOrNull(b.createdAt)?.getTime() ?? 0) - (toDateOrNull(a.createdAt)?.getTime() ?? 0));
        setRuns(next);
      },
      (err) => {
        console.error("Failed to load PDF scan runs:", err);
        setRuns([]);
      }
    );
  }, [previewMode, projektId, user?.uid]);

  useEffect(() => {
    if (previewMode) return;
    if (!user?.uid || !projektId || !activeRun?.id) {
      setDocRows([]);
      setDocRowsLoaded(false);
      return;
    }
    setDocRowsLoaded(false);
    const q = query(quellenFinderPdfScanDocsCol(firestoreClient, user.uid, projektId, activeRun.id), limit(200));
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs
          .map((entry) => ({ id: entry.id, ...(entry.data() as PdfScanDocSummaryDoc) }))
          .sort((a, b) => {
            const scoreDiff = readTopScore(b) - readTopScore(a);
            if (scoreDiff !== 0) return scoreDiff;
            const countDiff = Number(b.visibleSectionCount || 0) - Number(a.visibleSectionCount || 0);
            if (countDiff !== 0) return countDiff;
            return String(a.docTitle || a.pdfLabel || "").localeCompare(String(b.docTitle || b.pdfLabel || ""), "de");
          });
        setDocRows(next);
        setDocRowsLoaded(true);
      },
      (err) => {
        console.error("Failed to load pdfScanDocs:", err);
        setDocRows([]);
        setDocRowsLoaded(true);
      }
    );
  }, [activeRun?.id, previewMode, projektId, user?.uid]);

  useEffect(() => {
    if (previewMode) return;
    if (!user?.uid || !projektId || !activeRun?.id || !activeDocId) {
      setSectionRows([]);
      setSectionRowsLoaded(false);
      return;
    }
    setSectionRowsLoaded(false);
    const q = query(
      quellenFinderPdfScanSectionsCol(firestoreClient, user.uid, projektId, activeRun.id),
      where("docId", "==", activeDocId),
      limit(200)
    );
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs
          .map((entry) => ({ id: entry.id, ...(entry.data() as PdfScanResultDoc) }))
          .sort((a, b) => {
            const scoreDiff = Number(b.score0To100 || 0) - Number(a.score0To100 || 0);
            if (scoreDiff !== 0) return scoreDiff;
            const rankDiff = Number(a.docRank || 9999) - Number(b.docRank || 9999);
            if (rankDiff !== 0) return rankDiff;
            return Number(a.pageStart || 9999) - Number(b.pageStart || 9999);
          });
        setSectionRows(next);
        setSectionRowsLoaded(true);
      },
      (err) => {
        console.error("Failed to load pdfScanSections:", err);
        setSectionRows([]);
        setSectionRowsLoaded(true);
      }
    );
  }, [activeDocId, activeRun?.id, previewMode, projektId, user?.uid]);

  useEffect(() => {
    if (!previewMode) return;
    if (!activeDocId) {
      setSectionRows([]);
      setSectionRowsLoaded(false);
      return;
    }
    setSectionRows(preview?.sectionsByDocId?.[activeDocId] ?? []);
    setSectionRowsLoaded(true);
  }, [activeDocId, previewMode, preview]);

  useEffect(() => {
    const running = activeRun?.status === "queued" || activeRun?.status === "running";
    if (!running) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [activeRun?.status]);

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
        toast.success("PDF-Scan abgeschlossen", {
          description:
            typeof activeRun.pdfScanSectionCount === "number"
              ? `${formatIntDe(activeRun.pdfScanSectionCount)} sichtbare Sections`
              : undefined,
        });
      } else if (nextStatus === "error") {
        toast.error("PDF-Scan fehlgeschlagen", {
          description: String(activeRun.errorMessage || "").trim() || "Unbekannter Fehler",
        });
      } else if (nextStatus === "cancelled") {
        toast.success("PDF-Scan abgebrochen", { description: `Run: ${activeRun.id}` });
      }
    }

    lastRunStatus.current = { runId: activeRun.id, status: nextStatus };
  }, [activeRun?.errorMessage, activeRun?.id, activeRun?.pdfScanSectionCount, activeRun?.status]);

  const selectKapitel = (kapitelId: string | null) => {
    setSelectedKapitelId(kapitelId);
    setActiveDocId(null);
    setExtractOpen(false);
    setExtractRequest(null);
    if (!kapitelId) {
      setActiveRunId(null);
      return;
    }
    const mostRecentRun = pdfScanRuns.find((run) => Array.isArray(run.kapitelIds) && run.kapitelIds.includes(kapitelId));
    setActiveRunId(mostRecentRun?.id ?? null);
  };

  const selectRun = (run: RunRow) => {
    setActiveRunId(run.id);
    const kapitelId = Array.isArray(run.kapitelIds) ? String(run.kapitelIds[0] || "").trim() : "";
    if (kapitelId) setSelectedKapitelId(kapitelId);
  };

  const togglePdfSelection = (pdfId: string, nextChecked: boolean) => {
    setSelectedPdfIds((prev) => {
      const next = new Set(prev);
      if (nextChecked) next.add(pdfId);
      else next.delete(pdfId);
      return Array.from(next);
    });
  };

  const allVisibleSelected = filteredPdfs.length > 0 && selectedVisibleCount === filteredPdfs.length;
  const someVisibleSelected = selectedVisibleCount > 0 && selectedVisibleCount < filteredPdfs.length;

  const setVisibleSelection = (checked: boolean) => {
    setSelectedPdfIds((prev) => {
      const next = new Set(prev);
      for (const pdf of filteredPdfs) {
        if (checked) next.add(pdf.id);
        else next.delete(pdf.id);
      }
      return Array.from(next);
    });
  };

  const uploadProjectPdfs = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (!user?.uid || !projektId) {
      toast.error("Nicht eingeloggt", { description: "User fehlt." });
      return;
    }

    const fileList = Array.from(files);
    const invalid = fileList.filter((file) => !String(file.name || "").toLowerCase().endsWith(".pdf"));
    if (invalid.length) {
      toast.error("Nur PDFs erlaubt", {
        description: invalid
          .map((file) => file.name)
          .slice(0, 3)
          .join(", "),
      });
      return;
    }

    setUploading(true);
    setUploadProgress({ done: 0, total: fileList.length });

    try {
      const storage = getStorage(firebaseApp);
      const col = projectPdfsCol(firestoreClient, user.uid, projektId);

      for (let index = 0; index < fileList.length; index += 1) {
        const file = fileList[index]!;
        const originalName = String(file.name || "document.pdf").trim() || "document.pdf";
        const safeName = originalName.replace(/[^a-zA-Z0-9._-]/g, "_");
        const suffix = safeName.toLowerCase().endsWith(".pdf") ? safeName : `${safeName}.pdf`;
        const stamp = `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
        const path = `users/${user.uid}/projects/${projektId}/pdfs/${stamp}_${suffix}`.slice(0, 900);

        setUploadProgress({ done: index, total: fileList.length });
        await uploadBytes(storageRef(storage, path), file, { contentType: "application/pdf" });

        const now = Timestamp.now();
        await addDoc(col, {
          filename: originalName,
          storagePath: path,
          size: Math.max(0, Math.trunc(file.size)),
          contentType: "application/pdf",
          createdAt: now,
          updatedAt: now,
        });
        setUploadProgress({ done: index + 1, total: fileList.length });
      }

      toast.success("PDFs hochgeladen", { description: `${fileList.length} Datei(en)` });
    } catch (err: unknown) {
      toast.error("Upload fehlgeschlagen", { description: err instanceof Error ? err.message : String(err) });
    } finally {
      setUploading(false);
      setUploadProgress(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const deleteProjectPdf = async (pdf: PdfRow) => {
    if (!user?.uid || !projektId) return;
    const confirmed = window.confirm(`PDF wirklich löschen?\n\n${pdf.filename}`);
    if (!confirmed) return;

    setDeletingPdfId(pdf.id);
    try {
      try {
        const path = String(pdf.storagePath || "").trim();
        if (path) {
          const storage = getStorage(firebaseApp);
          await deleteObject(storageRef(storage, path));
        }
      } catch (err: unknown) {
        toast.error("Storage delete fehlgeschlagen", { description: err instanceof Error ? err.message : String(err) });
        return;
      }

      try {
        await deleteDoc(doc(firestoreClient, "users", user.uid, "projects", projektId, "pdfs", pdf.id));
        setSelectedPdfIds((prev) => prev.filter((id) => id !== pdf.id));
        toast.success("PDF gelöscht", { description: pdf.filename });
      } catch (err: unknown) {
        toast.error("Firestore delete fehlgeschlagen", { description: err instanceof Error ? err.message : String(err) });
      }
    } finally {
      setDeletingPdfId((current) => (current === pdf.id ? null : current));
    }
  };

  const openStoredPdf = async (pdfId: string, anchorPage?: number | null) => {
    const meta = pdfsById.get(pdfId);
    const storagePath = String(meta?.storagePath || "").trim();
    if (!storagePath) {
      toast.error("PDF kann nicht geöffnet werden", { description: "Kein Storage-Pfad gefunden." });
      return;
    }

    const popup = window.open("about:blank", "_blank");
    if (!popup) {
      toast.error("PDF kann nicht geöffnet werden", { description: "Popup blockiert." });
      return;
    }

    try {
      const url = await getDownloadUrlFromStorage(storagePath);
      const page = typeof anchorPage === "number" && Number.isFinite(anchorPage) ? `#page=${Math.max(1, Math.round(anchorPage))}` : "";
      popup.location.href = `${url}${page}`;
    } catch (err: unknown) {
      try {
        popup.close();
      } catch {
        // ignore
      }
      toast.error("PDF kann nicht geöffnet werden", { description: err instanceof Error ? err.message : String(err) });
    }
  };

  const startPdfScan = async () => {
    if (!selectedKapitelId) {
      toast.error("Bitte zuerst ein Kapitel auswählen.");
      return;
    }
    if (selectedPdfIds.length === 0) {
      toast.error("Bitte mindestens ein PDF auswählen.");
      return;
    }
    if (projectRunningRun) {
      setActiveRunId(projectRunningRun.id);
      toast.error("Es läuft bereits ein PDF-Scan", { description: `Run: ${projectRunningRun.id}` });
      return;
    }

    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session-Token fehlt." });
      return;
    }

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/pdf-scan`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        projekt_id: projektId,
        kapitel_id: selectedKapitelId,
        pdf_ids: selectedPdfIds,
      }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      if (res.status === 402) {
        toast.error("Nicht genügend Credits", { description: detail });
        return;
      }
      if (res.status === 409) {
        toast.error("PDF-Scan läuft bereits", { description: detail });
        return;
      }
      toast.error("PDF-Scan konnte nicht gestartet werden", { description: detail });
      return;
    }

    const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const runId = typeof payload.run_id === "string" ? payload.run_id : "";
    if (runId) setActiveRunId(runId);
    toast.success("PDF-Scan gestartet", { description: runId ? `Run: ${runId}` : undefined });
  };

  const cancelPdfScan = async () => {
    if (!activeRun?.id) return;

    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session-Token fehlt." });
      return;
    }

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/pdf-scan/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        projekt_id: projektId,
        run_id: activeRun.id,
      }),
    });

    if (!res.ok) {
      toast.error("Abbruch fehlgeschlagen", { description: await readFastApiError(res) });
      return;
    }

    toast.success("Abbruch angefordert", { description: `Run: ${activeRun.id}` });
  };

  const filteredDocRows = useMemo(() => {
    const q = resultFilter.trim().toLowerCase();
    if (!q) return docRows;
    return docRows.filter((row) => {
      const previewTitles = (row.previewSections || [])
        .map((section) => String(section.title || "").trim())
        .filter(Boolean)
        .join("\n");
      const haystack = [row.docTitle, row.pdfLabel, row.pdfFilename, row.topSectionTitle, previewTitles]
        .map((part) => String(part || "").toLowerCase())
        .join("\n");
      return haystack.includes(q);
    });
  }, [docRows, resultFilter]);

  const running = activeRun?.status === "queued" || activeRun?.status === "running";
  const isDone = activeRun?.status === "success" || String(activeRun?.progress?.stage || "") === "done";
  const isError = activeRun?.status === "error" || String(activeRun?.progress?.stage || "") === "error";
  const isCancelled = activeRun?.status === "cancelled" || String(activeRun?.progress?.stage || "") === "cancelled";
  const isCancelRequested =
    Boolean(activeRun?.cancelRequestedAt) || String(activeRun?.progress?.stage || "") === "cancel_requested";

  const runStartedAt = toDateOrNull(activeRun?.startedAt) ?? toDateOrNull(activeRun?.createdAt);
  const runFinishedAt = toDateOrNull(activeRun?.finishedAt);
  const runStartMs = runStartedAt?.getTime() ?? Date.now();
  const stageStartMs =
    (toDateOrNull(activeRun?.progress?.stageStartedAt) ?? runStartedAt)?.getTime() ?? runStartMs;
  const elapsedMs =
    running
      ? Math.max(0, nowMs - runStartMs)
      : runFinishedAt && runStartedAt
        ? runFinishedAt.getTime() - runStartedAt.getTime()
        : 0;
  const stageElapsedMs = running ? Math.max(0, nowMs - stageStartMs) : 0;

  const stageKey = String(activeRun?.progress?.stage || "");
  const activeStepIndex = PDF_SCAN_PIPELINE_STEPS.findIndex((step) => step.key === stageKey);
  const completedStepCount = isDone ? PDF_SCAN_PIPELINE_STEPS.length : Math.max(0, activeStepIndex);
  const currentRatio =
    typeof activeRun?.progress?.current === "number" &&
    typeof activeRun?.progress?.total === "number" &&
    activeRun.progress.total > 0
      ? Math.max(0, Math.min(1, activeRun.progress.current / activeRun.progress.total))
      : 0;
  const progressValue =
    isDone || isCancelled
      ? 100
      : activeStepIndex < 0
        ? 0
        : ((activeStepIndex + currentRatio) / PDF_SCAN_PIPELINE_STEPS.length) * 100;

  const visibleDocCount =
    typeof activeRun?.pdfScanDocCount === "number" ? activeRun.pdfScanDocCount : docRows.length;
  const visibleSectionCount =
    typeof activeRun?.pdfScanSectionCount === "number"
      ? activeRun.pdfScanSectionCount
      : docRows.reduce((sum, row) => sum + (typeof row.visibleSectionCount === "number" ? row.visibleSectionCount : 0), 0);
  const usefulPdfCount =
    typeof activeRun?.usefulPdfCount === "number"
      ? activeRun.usefulPdfCount
      : docRows.filter((row) => row.hasUsefulInformation === true).length;

  const activeKapitelSnapshot = activeRun?.kapitelSnapshots?.[0] ?? null;
  const chapterNummer = String(activeKapitelSnapshot?.nummer ?? selectedKapitel?.nummer ?? "").trim();
  const chapterTitle = String(activeKapitelSnapshot?.title ?? selectedKapitel?.title ?? "").trim();
  const chapterHeading = `${chapterNummer ? `${chapterNummer} ` : ""}${chapterTitle || "Kapitel"}`.trim();
  const chapterThema = String(activeKapitelSnapshot?.thema ?? selectedKapitel?.thema ?? "").trim();

  const canStart = !previewMode && Boolean(selectedKapitelId) && selectedPdfIds.length > 0 && !uploading && !projectRunningRun;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(15,23,42,0.07),transparent_38%),linear-gradient(180deg,rgba(249,250,251,0.96),rgba(244,246,248,0.96))]">
        <div className="mx-auto flex min-h-screen max-w-[1820px] flex-col lg:flex-row">
          <aside className="flex w-full shrink-0 flex-col border-b border-sidebar-border bg-sidebar/95 backdrop-blur lg:max-w-[372px] lg:border-r lg:border-b-0">
            <div className="border-b border-sidebar-border px-5 py-5">
              <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm text-sidebar-foreground/80 transition-colors hover:text-sidebar-foreground">
                <ArrowLeft className="h-4 w-4" />
                Zurück zum Dashboard
              </Link>
              <div className="mt-5">
                <div className="text-[32px] font-semibold tracking-[-0.03em] text-sidebar-foreground">PDF-Scan</div>
                <div className="mt-2 text-sm leading-6 text-sidebar-foreground/70">
                  Finale Sections aus der neuen Langlauf-Pipeline. Angezeigt werden nur Scores ab <span className="font-medium text-sidebar-foreground">5</span>.
                </div>
                <div className="mt-4 inline-flex items-center rounded-full border border-sidebar-border bg-sidebar-accent/60 px-3 py-1 text-xs text-sidebar-foreground/80">
                  Projekt: <span className="ml-1 font-medium text-sidebar-foreground">{projektName}</span>
                </div>
              </div>
            </div>

            <div className="space-y-5 px-5 py-5">
              <Card className="border-sidebar-border bg-sidebar-accent/25 shadow-none">
                <div className="p-4">
                  <div className="text-sm font-semibold text-sidebar-foreground">Kapitel</div>
                  <div className="mt-1 text-xs text-sidebar-foreground/70">Der Scan läuft immer für genau ein Kapitel.</div>
                  <Select value={selectedKapitelId ?? undefined} onValueChange={(value) => selectKapitel(value || null)}>
                    <SelectTrigger className="mt-3 h-10 w-full border-sidebar-border bg-background/80">
                      <SelectValue placeholder="Kapitel auswählen" />
                    </SelectTrigger>
                    <SelectContent>
                      {kapitels.map((kapitel) => (
                        <SelectItem key={kapitel.id} value={kapitel.id}>
                          <span className="truncate">
                            {`${"".padStart(kapitelDepth(kapitel.nummer) * 2, " ")}${kapitel.nummer ? `${kapitel.nummer} ` : ""}${kapitel.title}`.trim()}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </Card>

              <Card className="border-sidebar-border bg-sidebar-accent/25 shadow-none">
                <div className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-sidebar-foreground">PDF-Bibliothek</div>
                      <div className="mt-1 text-xs text-sidebar-foreground/70">
                        {formatIntDe(selectedPdfIds.length)} von {formatIntDe(pdfs.length)} ausgewählt
                        {pdfLibraryFilter.trim() ? ` • ${formatIntDe(filteredPdfs.length)} sichtbar` : ""}
                        {selectedPdfIds.length > 0 ? ` • ${formatBytes(selectedPdfBytes)}` : ""}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-sidebar-border bg-background/80"
                      disabled={uploading || previewMode}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      {uploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileUp className="mr-2 h-4 w-4" />}
                      Upload
                    </Button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="application/pdf,.pdf"
                      multiple
                      className="hidden"
                      onChange={(event) => void uploadProjectPdfs(event.target.files)}
                    />
                  </div>

                  {uploadProgress ? (
                    <div className="mt-3 rounded-md border border-sidebar-border bg-background/70 px-3 py-2 text-xs text-sidebar-foreground/80">
                      Upload läuft: {formatIntDe(uploadProgress.done)} / {formatIntDe(uploadProgress.total)}
                    </div>
                  ) : null}

                  <div className="mt-4 flex items-center gap-2">
                    <Input
                      value={pdfLibraryFilter}
                      onChange={(event) => setPdfLibraryFilter(event.target.value)}
                      placeholder="PDFs filtern…"
                      className="h-9 border-sidebar-border bg-background/80"
                    />
                    {pdfLibraryFilter.trim() ? (
                      <Button
                        size="icon"
                        variant="outline"
                        className="h-9 w-9 border-sidebar-border bg-background/80"
                        onClick={() => setPdfLibraryFilter("")}
                        title="Filter löschen"
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    ) : null}
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-sidebar-border bg-background/70 px-3 py-2">
                    <div className="flex items-center gap-2 text-xs text-sidebar-foreground/80">
                      <Checkbox
                        checked={allVisibleSelected ? true : someVisibleSelected ? "indeterminate" : false}
                        onCheckedChange={(checked) => setVisibleSelection(Boolean(checked))}
                      />
                      {pdfLibraryFilter.trim() ? "Sichtbare PDFs auswählen" : "Alle PDFs auswählen"}
                    </div>
                    <Badge variant="outline" className="border-sidebar-border bg-background/80 tabular-nums">
                      {formatIntDe(filteredPdfs.length)}
                    </Badge>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto h-7 px-2 text-xs text-sidebar-foreground/75 hover:text-sidebar-foreground"
                      onClick={() => setSelectedPdfIds([])}
                      disabled={selectedPdfIds.length === 0}
                    >
                      Auswahl löschen
                    </Button>
                  </div>

                  <ScrollArea className="mt-3 h-[380px] xl:h-[460px]">
                    <div className="space-y-2 pr-3">
                      {pdfs.length === 0 ? (
                        <div className="rounded-md border border-dashed border-sidebar-border px-3 py-5 text-center text-xs text-sidebar-foreground/70">
                          Noch keine PDFs hochgeladen.
                        </div>
                      ) : filteredPdfs.length === 0 ? (
                        <div className="rounded-md border border-dashed border-sidebar-border px-3 py-5 text-center text-xs text-sidebar-foreground/70">
                          Keine PDFs passen zum aktuellen Filter.
                        </div>
                      ) : (
                        filteredPdfs.map((pdf) => {
                          const isSelected = selectedPdfIdSet.has(pdf.id);
                          const isDeleting = deletingPdfId === pdf.id;
                          return (
                            <div
                              key={pdf.id}
                              className={`max-w-full overflow-hidden rounded-xl border transition-all ${
                                isSelected
                                  ? "border-primary/40 bg-background shadow-sm ring-1 ring-primary/10"
                                  : "border-sidebar-border bg-background/70 hover:bg-background/90"
                              }`}
                            >
                              <div
                                role="button"
                                tabIndex={0}
                                onClick={() => togglePdfSelection(pdf.id, !isSelected)}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    togglePdfSelection(pdf.id, !isSelected);
                                  }
                                }}
                                className="cursor-pointer px-3 py-3 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/30"
                              >
                                <div className="flex items-start gap-3">
                                  <Checkbox
                                    checked={isSelected}
                                    onClick={(event) => event.stopPropagation()}
                                    onCheckedChange={(checked) => togglePdfSelection(pdf.id, Boolean(checked))}
                                    className="mt-0.5"
                                  />
                                  <div className="min-w-0 flex-1">
                                    <div className="truncate text-sm font-medium text-sidebar-foreground" title={pdf.filename}>
                                      {pdf.filename}
                                    </div>
                                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-sidebar-foreground/65">
                                      <span>{formatBytes(pdf.size)}</span>
                                      {isSelected ? (
                                        <Badge variant="outline" className="h-5 border-primary/25 bg-primary/5 px-1.5 text-[10px] font-medium">
                                          ausgewählt
                                        </Badge>
                                      ) : null}
                                    </div>
                                  </div>
                                </div>
                              </div>

                              <div className="flex min-w-0 items-center justify-between gap-2 border-t border-sidebar-border/70 bg-background/45 px-3 py-2">
                                <div className="min-w-0 truncate text-[11px] text-sidebar-foreground/55">
                                  {isSelected ? "Für den nächsten Scan markiert" : "Klicken zum Auswählen"}
                                </div>
                                <div className="flex shrink-0 items-center gap-1">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 gap-1 px-2 text-[11px]"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      void openStoredPdf(pdf.id);
                                    }}
                                    title="PDF öffnen"
                                  >
                                    <ExternalLink className="h-3.5 w-3.5" />
                                    Öffnen
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 gap-1 px-2 text-[11px] text-destructive hover:text-destructive"
                                    disabled={isDeleting || previewMode}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      void deleteProjectPdf(pdf);
                                    }}
                                    title="PDF löschen"
                                  >
                                    {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                                    Löschen
                                  </Button>
                                </div>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </ScrollArea>

                  <Button size="lg" onClick={startPdfScan} disabled={!canStart} className="mt-4 w-full">
                    {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                    Scan starten
                  </Button>

                  {projectRunningRun && projectRunningRun.id !== activeRun?.id ? (
                    <div className="mt-3 text-xs leading-5 text-sidebar-foreground/70">
                      Es läuft bereits ein anderer Scan im Projekt. Wähle ihn unten aus, um den Status zu verfolgen.
                    </div>
                  ) : null}
                </div>
              </Card>
            </div>

            <Separator className="bg-sidebar-border" />

            <div className="min-h-0 flex-1 overflow-hidden">
              <div className="px-5 py-4 text-sm font-semibold text-sidebar-foreground">Runs</div>
              <div className="h-full overflow-auto divide-y divide-sidebar-border">
                {pdfScanRuns.length === 0 ? (
                  <SidebarEmptyState label="Noch keine PDF-Scans." />
                ) : (
                  pdfScanRuns.map((run) => {
                    const snapshot = run.kapitelSnapshots?.[0] ?? null;
                    const label = `${snapshot?.nummer ? `${snapshot.nummer} ` : ""}${snapshot?.title || run.id}`.trim();
                    const subtitle =
                      run.status === "queued" || run.status === "running"
                        ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  Läuft…`
                        : run.status === "success"
                          ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  ${formatIntDe(run.pdfScanSectionCount ?? run.resultCount ?? 0)} Sections`
                          : run.status === "cancelled"
                            ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  Abgebrochen`
                            : `${formatTimeHm(run.startedAt ?? run.createdAt)}  Fehler`;
                    const active = run.id === activeRun?.id;
                    const icon =
                      run.status === "queued" || run.status === "running" ? (
                        <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
                      ) : run.status === "success" ? (
                        <Check className="h-4 w-4 text-emerald-600" />
                      ) : run.status === "cancelled" ? (
                        <Ban className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <AlertTriangle className="h-4 w-4 text-red-600" />
                      );

                    return (
                      <button
                        key={run.id}
                        type="button"
                        onClick={() => selectRun(run)}
                        className={`w-full px-5 py-3 text-left transition-colors hover:bg-sidebar-accent/70 ${
                          active ? "bg-sidebar-accent" : ""
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-sidebar-foreground">{label}</div>
                            <div className="mt-1 truncate text-xs text-sidebar-foreground/70">{subtitle}</div>
                          </div>
                          <div className="shrink-0 pt-0.5">{icon}</div>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          </aside>

          <main className="min-w-0 flex-1 overflow-visible lg:overflow-auto">
            <div className="mx-auto max-w-[1320px] space-y-6 px-4 py-4 sm:px-6 sm:py-6">
              <Card className="overflow-hidden border-border/70 shadow-sm">
                <div className="bg-[linear-gradient(135deg,rgba(15,23,42,0.05),rgba(255,255,255,0.9)),radial-gradient(circle_at_top_right,rgba(20,184,166,0.14),transparent_42%)] p-6">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-[28px] font-semibold tracking-[-0.03em] text-foreground">{chapterHeading || "Kapitel auswählen"}</div>
                      <div className="mt-2 text-sm text-muted-foreground">
                        {activeRun ? (
                          <>
                            Gestartet: {formatDateTimeWithSeconds(runStartedAt)}
                            {runFinishedAt ? <> | Abgeschlossen: {formatDateTimeWithSeconds(runFinishedAt)}</> : null}
                          </>
                        ) : selectedKapitel ? (
                          "Noch kein PDF-Scan für dieses Kapitel. Starte links einen neuen Lauf."
                        ) : (
                          "Wähle links ein Kapitel, lade PDFs hoch und starte dann die Pipeline."
                        )}
                      </div>
                      {chapterThema ? (
                        <div className="mt-3 max-w-[860px] text-sm leading-7 text-muted-foreground">{chapterThema}</div>
                      ) : null}
                    </div>

                    {activeRun ? (
                      <div className="flex flex-wrap items-center justify-end gap-3">
                        <StatusPill status={String(activeRun.status || "")} />
                        {running ? (
                          <>
                            <Badge variant="outline" className="tabular-nums">
                              {formatElapsedShort(elapsedMs)} gesamt
                            </Badge>
                            <Badge variant="outline" className="tabular-nums">
                              {formatElapsedShort(stageElapsedMs)} Phase
                            </Badge>
                            <Button size="sm" variant="outline" onClick={cancelPdfScan} disabled={isCancelRequested}>
                              {isCancelRequested ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <X className="mr-2 h-4 w-4" />}
                              {isCancelRequested ? "Wird abgebrochen…" : "Abbrechen"}
                            </Button>
                          </>
                        ) : (
                          <>
                            <Badge variant="outline" className="tabular-nums">
                              {formatIntDe(visibleDocCount)} PDFs
                            </Badge>
                            <Badge variant="outline" className="tabular-nums">
                              {formatIntDe(visibleSectionCount)} Sections
                            </Badge>
                            <Badge variant="outline" className="tabular-nums">
                              {formatIntDe(usefulPdfCount)} nützlich
                            </Badge>
                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                </div>
              </Card>

              {activeRun ? (
                <Card className="overflow-hidden border-border/70 shadow-sm">
                  <div className="border-b border-border/70 bg-muted/20 px-5 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold">Pipeline-Status</div>
                        <div className="mt-1 text-xs text-muted-foreground">{stageLabel(activeRun)}</div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span className="tabular-nums">{formatIntDe(completedStepCount)} / {formatIntDe(PDF_SCAN_PIPELINE_STEPS.length)} Schritte</span>
                        {activeRun.hadPartialFailures ? (
                          <Badge
                            variant="outline"
                            className="border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/20 dark:text-amber-200"
                          >
                            Partial failures
                          </Badge>
                        ) : null}
                      </div>
                    </div>
                    <Progress value={progressValue} className="mt-4 h-2.5" />
                  </div>

                  <div className="grid grid-cols-2 gap-3 p-5 md:grid-cols-5">
                    {PDF_SCAN_PIPELINE_STEPS.map((step, index) => {
                      const done = isDone || index < activeStepIndex;
                      const active = !isDone && !isError && !isCancelled && index === activeStepIndex;
                      const classes = done
                        ? "border-emerald-300 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/20"
                        : active
                          ? "border-primary/35 bg-primary/5"
                          : "border-border bg-background";
                      return (
                        <div key={step.key} className={`rounded-xl border px-3 py-3 ${classes}`}>
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-xs font-medium">{step.label}</div>
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
                          <div className="mt-1 text-[11px] text-muted-foreground">{step.key}</div>
                        </div>
                      );
                    })}
                  </div>

                  {isError ? (
                    <div className="border-t border-border bg-destructive/5 px-5 py-4 text-sm text-destructive">
                      {String(activeRun.errorMessage || "").trim() || "Unbekannter Fehler"}
                    </div>
                  ) : null}
                </Card>
              ) : null}

              {!activeRun ? (
                <MainEmptyState selectedKapitel={selectedKapitel} />
              ) : (
                <Card className="border-border/70 shadow-sm">
                  <div className="border-b border-border/70 px-5 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold">Finale Section Scores</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          Ein Card pro PDF. Angezeigt werden nur finale Sections mit Score <span className="font-medium text-foreground">&gt;= 5</span>.
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="tabular-nums">
                          {formatIntDe(filteredDocRows.length)} PDFs
                        </Badge>
                        <Badge variant="outline" className="tabular-nums">
                          {formatIntDe(visibleSectionCount)} Sections
                        </Badge>
                        <Input
                          value={resultFilter}
                          onChange={(event) => setResultFilter(event.target.value)}
                          placeholder="PDF oder Section suchen…"
                          className="h-9 w-full sm:w-[280px]"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="p-5">
                    {!docRowsLoaded ? (
                      <ResultSkeleton />
                    ) : filteredDocRows.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-border bg-muted/10 px-5 py-12 text-center">
                        <div className="text-base font-medium">
                          {running ? "Noch keine finalen Ergebnisse" : "Keine sichtbaren Sections"}
                        </div>
                        <div className="mt-2 text-sm leading-7 text-muted-foreground">
                          {running
                            ? "Die Cards erscheinen erst nach Phase G und dem Persistieren der Ergebnisse."
                            : "Für diesen Lauf wurden keine finalen Sections mit Score >= 5 gespeichert."}
                        </div>
                      </div>
                    ) : (
                      <Accordion
                        type="single"
                        collapsible
                        value={activeDocId ?? ""}
                        onValueChange={(value) => setActiveDocId(value || null)}
                        className="space-y-4"
                      >
                        {filteredDocRows.map((pdfDoc) => {
                          const pdfMeta = pdfsById.get(String(pdfDoc.pdfId || ""));
                          const topScore = typeof pdfDoc.topSectionScore === "number" ? pdfDoc.topSectionScore : null;
                          const isOpen = activeDocId === pdfDoc.id;
                          const previewSections = (pdfDoc.previewSections || []).slice(0, 3);

                          return (
                            <AccordionItem key={pdfDoc.id} value={pdfDoc.id} className="overflow-hidden rounded-2xl border border-border bg-background shadow-sm">
                              <AccordionTrigger className="px-5 py-5 hover:no-underline">
                                <div className="flex min-w-0 flex-1 flex-col gap-4 text-left lg:flex-row lg:items-start lg:justify-between">
                                  <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-start gap-3">
                                      <div className={`inline-flex h-10 min-w-[72px] items-center justify-center rounded-xl border px-3 text-sm font-semibold tabular-nums ${scoreToneClasses(topScore)}`}>
                                        {topScore !== null ? formatScore(topScore) : "—"}
                                      </div>
                                      <div className="min-w-0 flex-1">
                                        <div className="line-clamp-2 text-base font-semibold leading-6 text-foreground">
                                          {pdfDoc.docTitle || pdfDoc.pdfLabel || "Unbenanntes PDF"}
                                        </div>
                                        <div className="mt-1 text-sm text-muted-foreground">
                                          {pdfDoc.pdfFilename || pdfDoc.pdfLabel || "PDF"}
                                        </div>
                                      </div>
                                    </div>

                                    <div className="mt-4 flex flex-wrap gap-2">
                                      <Badge variant="outline" className="tabular-nums">
                                        {formatIntDe(pdfDoc.visibleSectionCount ?? 0)} Sections
                                      </Badge>
                                      {typeof pdfDoc.docMatchProbability === "number" ? (
                                        <Badge variant="outline" className="tabular-nums">
                                          p={formatProbability(pdfDoc.docMatchProbability)}
                                        </Badge>
                                      ) : null}
                                      {typeof pdfDoc.pageCount === "number" ? (
                                        <Badge variant="outline" className="tabular-nums">
                                          {formatIntDe(pdfDoc.pageCount)} Seiten
                                        </Badge>
                                      ) : null}
                                      {typeof pdfDoc.acceptedHeadingCount === "number" ? (
                                        <Badge variant="outline" className="tabular-nums">
                                          {formatIntDe(pdfDoc.acceptedHeadingCount)} Headings
                                        </Badge>
                                      ) : null}
                                      {pdfDoc.doclingStatus ? <Badge variant="outline">{pdfDoc.doclingStatus}</Badge> : null}
                                    </div>

                                    {previewSections.length > 0 ? (
                                      <div className="mt-4 flex flex-wrap gap-2">
                                        {previewSections.map((section, index) => (
                                          <div
                                            key={`${pdfDoc.id}_${section.sectionId ?? index}`}
                                            className="rounded-full border border-border bg-muted/30 px-3 py-1 text-xs text-muted-foreground"
                                          >
                                            <span className="font-medium text-foreground">{formatScore(section.score0To100)}</span>
                                            <span className="mx-1 text-muted-foreground/70">•</span>
                                            <span>{section.title || "Section"}</span>
                                            <span className="mx-1 text-muted-foreground/70">•</span>
                                            <span>{formatPageRange(section.pageStart, section.pageEnd)}</span>
                                          </div>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>

                                  <div className="shrink-0">
                                    <div className="rounded-xl border border-border bg-muted/20 px-3 py-2 text-right">
                                      <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Top Section</div>
                                      <div className="mt-1 max-w-[260px] truncate text-sm font-medium text-foreground">
                                        {pdfDoc.topSectionTitle || "—"}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              </AccordionTrigger>

                              <AccordionContent className="px-5 pb-5">
                                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-5">
                                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                    <span>{pdfDoc.strategy ? `Strategie: ${pdfDoc.strategy}` : "Section-first locator preview"}</span>
                                    {pdfDoc.hasUsefulInformation === true ? (
                                      <Badge
                                        variant="outline"
                                        className="border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/20 dark:text-emerald-200"
                                      >
                                        useful
                                      </Badge>
                                    ) : null}
                                  </div>

                                  <div className="flex flex-wrap items-center gap-2">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => {
                                        setDetailsDoc(pdfDoc);
                                        setDetailsOpen(true);
                                      }}
                                    >
                                      <BarChart3 className="mr-2 h-4 w-4" />
                                      Pipeline Details
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      disabled={!pdfMeta?.storagePath}
                                      onClick={() => void openStoredPdf(String(pdfDoc.pdfId || ""))}
                                    >
                                      <ExternalLink className="mr-2 h-4 w-4" />
                                      PDF öffnen
                                    </Button>
                                  </div>
                                </div>

                                <div className="mt-4 space-y-3">
                                  {!isOpen || !sectionRowsLoaded ? (
                                    <div className="space-y-3">
                                      {isOpen
                                        ? Array.from({ length: 2 }).map((_, idx) => (
                                            <Card key={idx} className="p-4">
                                              <Skeleton className="h-5 w-2/3" />
                                              <Skeleton className="mt-3 h-4 w-1/2" />
                                              <Skeleton className="mt-4 h-20 w-full" />
                                            </Card>
                                          ))
                                        : null}
                                    </div>
                                  ) : sectionRows.length === 0 ? (
                                    <div className="rounded-xl border border-dashed border-border bg-muted/10 px-4 py-8 text-center text-sm text-muted-foreground">
                                      Für dieses PDF wurden keine finalen Sections geladen.
                                    </div>
                                  ) : (
                                    sectionRows.map((section) => {
                                      const sectionScore =
                                        typeof section.score0To100 === "number" ? section.score0To100 : null;
                                      return (
                                        <Card key={section.id} className="overflow-hidden border-border/80 shadow-none">
                                          <div className="p-4">
                                            <div className="flex flex-wrap items-start justify-between gap-4">
                                              <div className="min-w-0 flex-1">
                                                <div className="flex flex-wrap items-center gap-2">
                                                  <div className={`inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold tabular-nums ${scoreToneClasses(sectionScore)}`}>
                                                    {sectionScore !== null ? formatScore(sectionScore) : "—"}
                                                  </div>
                                                  <Badge variant="outline" className="tabular-nums">
                                                    {formatPageRange(section.pageStart, section.pageEnd)}
                                                  </Badge>
                                                  {section.scoreBand ? <Badge variant="outline">{section.scoreBand}</Badge> : null}
                                                  {typeof section.supportingPassageCount === "number" ? (
                                                    <Badge variant="outline" className="tabular-nums">
                                                      {formatIntDe(section.supportingPassageCount)} Evidenz
                                                    </Badge>
                                                  ) : null}
                                                </div>

                                                <div className="mt-3 line-clamp-2 text-base font-semibold leading-6">{section.title || section.sectionPathText || "Untitled section"}</div>
                                                {section.sectionPathText && section.sectionPathText !== section.title ? (
                                                  <div className="mt-1 text-sm text-muted-foreground">{section.sectionPathText}</div>
                                                ) : null}

                                                <div className="mt-3 flex flex-wrap gap-2">
                                                  {(section.subpointCoverageIds || []).slice(0, 8).map((subpointId) => (
                                                    <Badge key={`${section.id}_${subpointId}`} variant="outline">
                                                      {subpointId}
                                                    </Badge>
                                                  ))}
                                                  {typeof section.supportStrength === "number" ? (
                                                    <Badge variant="outline" className="tabular-nums">
                                                      Support {formatScore(section.supportStrength, 3)}
                                                    </Badge>
                                                  ) : null}
                                                </div>
                                              </div>

                                              <div className="shrink-0">
                                                <Button
                                                  size="sm"
                                                  onClick={() => {
                                                    setExtractRequest({
                                                      projektId,
                                                      runId: String(activeRun?.id || ""),
                                                      pdfDocId: String(pdfDoc.id),
                                                      sectionDocId: String(section.id),
                                                      pdfId: String(section.pdfId || "") || undefined,
                                                      pdfFilename: section.pdfFilename || pdfDoc.pdfFilename || pdfDoc.pdfLabel,
                                                      storagePath: pdfMeta?.storagePath,
                                                      anchorPage:
                                                        typeof section.anchorPage === "number" ? section.anchorPage : undefined,
                                                    });
                                                    setExtractOpen(true);
                                                  }}
                                                >
                                                  Preview
                                                </Button>
                                              </div>
                                            </div>

                                            {section.evidencePreview && section.evidencePreview.length > 0 ? (
                                              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                                                {section.evidencePreview.slice(0, 2).map((evidence, index) => (
                                                  <div key={`${section.id}_evidence_${index}`} className="rounded-xl border border-border bg-muted/20 p-3">
                                                    <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
                                                      <span>{formatPageRange(evidence.pageStart, evidence.pageEnd)}</span>
                                                      {(evidence.lanes || []).length > 0 ? (
                                                        <span>{(evidence.lanes || []).join(", ")}</span>
                                                      ) : null}
                                                    </div>
                                                    <div className="mt-2 text-sm leading-6 text-muted-foreground">{evidence.text || "—"}</div>
                                                  </div>
                                                ))}
                                              </div>
                                            ) : null}
                                          </div>
                                        </Card>
                                      );
                                    })
                                  )}
                                </div>
                              </AccordionContent>
                            </AccordionItem>
                          );
                        })}
                      </Accordion>
                    )}
                  </div>
                </Card>
              )}
            </div>
          </main>
        </div>

        <PdfExtractDialog open={extractOpen} onOpenChange={setExtractOpen} request={extractRequest} />
        <PdfScanDetailsDialog
          open={detailsOpen}
          onOpenChange={setDetailsOpen}
          uid={user?.uid || ""}
          projektId={projektId}
          runId={activeRun?.id || ""}
          pdfDoc={detailsDoc}
        />
      </div>
      <ViewportWarning />
    </TooltipProvider>
  );
}
