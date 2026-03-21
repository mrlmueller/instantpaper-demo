"use client";

import { memo, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import Link from "next/link";
import Cookies from "js-cookie";
import {
  Timestamp,
  limit,
  onSnapshot,
  orderBy,
  query,
  where,
} from "firebase/firestore";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  BookOpen,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronUp,
  Clock3,
  DollarSign,
  Eye,
  FileText,
  FileUp,
  FolderOpen,
  HardDrive,
  Loader2,
  Play,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

import type { Kapitel } from "@/app/actions/kapitels";
import { useAuth } from "@/app/components/providers/AuthProvider";
import { PdfExtractDialog, type PdfExtractRequest } from "@/app/components/quellen-finder/PdfExtractDialog";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import {
  projectPdfsCol,
  projectResearchRunsCol,
  quellenCol,
  quellenFinderPdfScanDocsCol,
  quellenFinderPdfScanSectionsCol,
} from "@/app/lib/firestore/refs";
import type {
  PdfScanDocSummaryDoc,
  PdfScanResultDoc,
  ProjectPdfDoc,
  QuelleDoc,
  QuellenFinderPipelineStage,
  QuellenFinderRunDoc,
} from "@/app/lib/firestore/types";
import { QUELLE_COLORS, colorMap, type QuelleColor } from "@/app/lib/quellen/fieldConfig";
import { cn } from "@/lib/utils";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type WithId<T> = T & { id: string };
type PdfRow = WithId<ProjectPdfDoc>;
type RunRow = WithId<QuellenFinderRunDoc>;
type PdfDocRow = WithId<PdfScanDocSummaryDoc>;
type PdfSectionRow = WithId<PdfScanResultDoc>;
type QuelleRow = WithId<QuelleDoc>;
type ToDateLike = { toDate: () => Date };
type PdfJsModule = typeof import("pdfjs-dist");
export type PdfScanWorkspacePreview = {
  pdfs: PdfRow[];
  runs: RunRow[];
  docRows: PdfDocRow[];
  sectionsByDocId: Record<string, PdfSectionRow[]>;
  initialSelectedKapitelId?: string | null;
  initialSelectedPdfIds?: string[];
  initialActiveRunId?: string | null;
  initialActiveDocId?: string | null;
  initialLibraryManagerOpen?: boolean;
};

const PDF_SCAN_PIPELINE_STEPS: Array<{ key: string; label: string; title: string; description: string }> = [
  { key: "prepare_inputs", label: "Inputs", title: "Inputs", description: "Prepare run inputs" },
  { key: "download_pdfs", label: "Download", title: "Download", description: "Download selected PDFs" },
  { key: "phase_a", label: "Phase A", title: "Phase A", description: "Build pipeline manifest" },
  { key: "phase_b", label: "Phase B", title: "Phase B", description: "Text extraction" },
  { key: "phase_c", label: "Phase C", title: "Phase C", description: "Normalize sections" },
  { key: "phase_d", label: "Phase D", title: "Phase D", description: "Plan retrieval" },
  { key: "phase_e", label: "Phase E", title: "Phase E", description: "Retrieve candidates" },
  { key: "phase_f", label: "Phase F", title: "Phase F", description: "Rerank candidates" },
  { key: "phase_g", label: "Phase G", title: "Phase G", description: "Score final sections" },
  { key: "persist_results", label: "Persist", title: "Persist", description: "Save UI results" },
];

const PDF_LIBRARY_COLOR_PICKER_ORDER: Array<QuelleColor | null> = [null, "rose", "peach", "cream", "green", "teal", "blue", "lavender"];

function hasToDate(value: unknown): value is ToDateLike {
  if (typeof value !== "object" || value === null) return false;
  const rec = value as Record<string, unknown>;
  return typeof rec.toDate === "function";
}

function toDateOrNull(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (typeof value === "string" || typeof value === "number") {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  if (typeof value === "object" && value !== null) {
    const rec = value as Record<string, unknown>;
    if (typeof rec.seconds === "number") {
      const millis = rec.seconds * 1000 + (typeof rec.nanoseconds === "number" ? rec.nanoseconds / 1_000_000 : 0);
      const date = new Date(millis);
      return Number.isNaN(date.getTime()) ? null : date;
    }
  }
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
  const fixed = n.toFixed(digits);
  return fixed.endsWith(".0") ? fixed.slice(0, -2) : fixed;
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

function formatDateShort(value: unknown): string {
  const d = toDateOrNull(value);
  if (!d) return "";
  return d.toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
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

function readPipelineStage(run: RunRow | null, stageKey: string): QuellenFinderPipelineStage | null {
  if (!run || typeof run.pipelineStages !== "object" || run.pipelineStages === null) return null;
  const raw = run.pipelineStages[stageKey];
  if (!raw || typeof raw !== "object") return null;
  return raw as QuellenFinderPipelineStage;
}

function readRunCostUsd(run: RunRow | null): number | null {
  if (!run || typeof run.summary !== "object" || run.summary === null) return null;
  const summary = run.summary as Record<string, unknown>;
  for (const key of ["total_cost_usd", "cost_usd", "estimated_cost_usd"]) {
    const n = Number(summary[key]);
    if (Number.isFinite(n) && n >= 0) return n;
  }
  const componentKeys = ["openai_estimated_cost_usd", "openai_embedding_estimated_cost_usd", "embedding_estimated_cost_usd"];
  const values = componentKeys
    .map((key) => Number(summary[key]))
    .filter((value) => Number.isFinite(value) && value >= 0);
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0);
}

function formatUsd(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  const digits = n >= 0.1 ? 2 : 3;
  return `$${n.toFixed(digits)}`;
}

function readTopScore(row: PdfDocRow): number {
  return typeof row.topSectionScore === "number" && Number.isFinite(row.topSectionScore) ? row.topSectionScore : -1;
}

let pdfjsUploadPromise: Promise<PdfJsModule> | null = null;

async function loadPdfJsForUpload(): Promise<PdfJsModule> {
  if (!pdfjsUploadPromise) pdfjsUploadPromise = import("pdfjs-dist") as Promise<PdfJsModule>;
  return pdfjsUploadPromise;
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

type DuplicateCheckResponse = {
  duplicate?: boolean;
  reason?: string | null;
  pdf_id?: string | null;
  filename?: string | null;
  error?: string | null;
};

function normalizePdfFilename(value: string): string {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function normalizeLibraryMatchKey(value: string): string {
  return String(value || "")
    .replace(/\.pdf$/i, "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return toHex(digest);
}

async function readPdfUploadMetadata(file: File): Promise<{ fileHash: string; pageCount: number | null }> {
  const bytes = await file.arrayBuffer();
  const fileHash = await sha256Hex(bytes);

  try {
    const pdfjs = await loadPdfJsForUpload();
    const loadingTask = pdfjs.getDocument(
      {
        data: new Uint8Array(bytes),
        disableWorker: true,
        isEvalSupported: false,
      } as unknown as Parameters<PdfJsModule["getDocument"]>[0]
    );
    const pdf = await loadingTask.promise;
    const pageCount = typeof pdf.numPages === "number" && Number.isFinite(pdf.numPages) ? pdf.numPages : null;
    await pdf.destroy();
    return { fileHash, pageCount };
  } catch {
    return { fileHash, pageCount: null };
  }
}

async function checkProjectPdfDuplicate(params: {
  projektId: string;
  filename: string;
  size: number;
  pageCount: number | null;
  fileHash: string;
}): Promise<DuplicateCheckResponse> {
  const res = await fetch("/api/quellen-finder/project-pdf-duplicate-check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      projekt_id: params.projektId,
      filename: params.filename,
      size: params.size,
      page_count: params.pageCount,
      file_hash: params.fileHash,
    }),
  });
  const payload = (await res.json().catch(() => ({}))) as DuplicateCheckResponse;
  if (!res.ok) {
    throw new Error(String(payload.error || "Duplikatsprüfung fehlgeschlagen."));
  }
  return payload;
}

const MainEmptyState = memo(function MainEmptyState({ selectedKapitel }: { selectedKapitel: Kapitel | null }) {
  return (
    <div className="flex min-h-full flex-1 items-center justify-center px-6">
      <div className="max-w-[640px] text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full border border-slate-200 bg-white shadow-sm">
          <FileText className="h-7 w-7 text-slate-400" />
        </div>
        <div className="mt-6 text-[26px] font-semibold tracking-[-0.03em] text-slate-950">PDF-Scan starten</div>
        <div className="mt-4 text-base leading-8 text-slate-500">
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
  preview,
}: {
  initialKapitels: Kapitel[];
  projektId: string;
  preview?: PdfScanWorkspacePreview;
}) {
  const { user } = useAuth();
  const previewMode = Boolean(preview);

  const kapitels = useMemo(() => initialKapitels ?? [], [initialKapitels]);
  const [selectedKapitelId, setSelectedKapitelId] = useState<string | null>(() => preview?.initialSelectedKapitelId ?? null);

  const [pdfs, setPdfs] = useState<PdfRow[]>(() => preview?.pdfs ?? []);
  const [selectedPdfIds, setSelectedPdfIds] = useState<string[]>(() => preview?.initialSelectedPdfIds ?? (preview?.pdfs ?? []).map((pdf) => pdf.id));
  const [pdfLibraryFilter, setPdfLibraryFilter] = useState("");
  const [libraryExpanded, setLibraryExpanded] = useState(true);
  const [libraryManagerOpen, setLibraryManagerOpen] = useState(() => Boolean(preview?.initialLibraryManagerOpen));
  const [libraryDragActive, setLibraryDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [deletingPdfId, setDeletingPdfId] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunRow[]>(() => preview?.runs ?? []);
  const [runsLoaded, setRunsLoaded] = useState(() => previewMode);
  const [activeRunId, setActiveRunId] = useState<string | null>(() => preview?.initialActiveRunId ?? null);
  const [activeRunCookieRestored, setActiveRunCookieRestored] = useState(() => previewMode);

  const [docRows, setDocRows] = useState<PdfDocRow[]>(() => preview?.docRows ?? []);
  const [docRowsLoaded, setDocRowsLoaded] = useState(() => previewMode);
  const [openDocIds, setOpenDocIds] = useState<string[]>(() => (preview?.docRows ?? []).map((row) => row.id));
  const [startConfirmOpen, setStartConfirmOpen] = useState(false);
  const [deleteConfirmPdf, setDeleteConfirmPdf] = useState<PdfRow | null>(null);

  const [sectionRowsByDocId, setSectionRowsByDocId] = useState<Record<string, PdfSectionRow[]>>(() => preview?.sectionsByDocId ?? {});
  const [sectionRowsLoaded, setSectionRowsLoaded] = useState(() => previewMode);

  const [extractOpen, setExtractOpen] = useState(false);
  const [extractRequest, setExtractRequest] = useState<PdfExtractRequest | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [projectQuellen, setProjectQuellen] = useState<QuelleRow[]>([]);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const libraryDragDepthRef = useRef(0);
  const pdfColorRequestSeqRef = useRef<Map<string, number>>(new Map());
  const lastRunStatus = useRef<{ runId: string; status: string } | null>(null);
  const previousActiveRunIdRef = useRef<string | null>(null);
  const knownDocIdsForRunRef = useRef<Set<string>>(new Set((preview?.docRows ?? []).map((row) => row.id)));
  const activeRunCookieKey = useMemo(() => `pdf_scan_active_run_${projektId}`, [projektId]);

  const selectedKapitel = useMemo(() => {
    if (!selectedKapitelId) return null;
    return kapitels.find((item) => item.id === selectedKapitelId) ?? null;
  }, [kapitels, selectedKapitelId]);

  const pdfsById = useMemo(() => {
    const map = new Map<string, PdfRow>();
    for (const pdf of pdfs) map.set(pdf.id, pdf);
    return map;
  }, [pdfs]);

  const projectQuellenWithColor = useMemo(
    () =>
      projectQuellen
        .filter((quelle) => Boolean(quelle.color))
        .map((quelle) => ({
          id: quelle.id,
          color: (quelle.color as QuelleColor | null) ?? null,
          key: normalizeLibraryMatchKey(quelle.title || ""),
        }))
        .filter((quelle) => quelle.color && quelle.key),
    [projectQuellen]
  );

  const pdfColorById = useMemo(() => {
    const map = new Map<string, QuelleColor | null>();
    for (const pdf of pdfs) {
      if (Object.prototype.hasOwnProperty.call(pdf, "color")) {
        map.set(pdf.id, (pdf.color as QuelleColor | null | undefined) ?? null);
        continue;
      }

      const pdfKey = normalizeLibraryMatchKey(pdf.filename || "");
      let matchedColor: QuelleColor | null = null;

      const exact = projectQuellenWithColor.find((quelle) => quelle.key === pdfKey);
      if (exact?.color) {
        matchedColor = exact.color;
      } else {
        const fuzzy = [...projectQuellenWithColor]
          .sort((a, b) => b.key.length - a.key.length)
          .find((quelle) => pdfKey.includes(quelle.key) || quelle.key.includes(pdfKey));
        matchedColor = fuzzy?.color ?? null;
      }

      map.set(pdf.id, matchedColor);
    }
    return map;
  }, [pdfs, projectQuellenWithColor]);

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

  const selectedPdfRows = useMemo(
    () => pdfs.filter((pdf) => selectedPdfIdSet.has(pdf.id)),
    [pdfs, selectedPdfIdSet]
  );

  const filteredPdfs = useMemo(() => {
    const q = pdfLibraryFilter.trim().toLowerCase();
    const filtered = q ? pdfs.filter((pdf) => String(pdf.filename || "").toLowerCase().includes(q)) : pdfs;
    const colorOrder = [...QUELLE_COLORS, null] as Array<QuelleColor | null>;
    return [...filtered].sort((a, b) => {
      const aColor = pdfColorById.get(a.id) ?? null;
      const bColor = pdfColorById.get(b.id) ?? null;
      const aIndex = colorOrder.indexOf(aColor);
      const bIndex = colorOrder.indexOf(bColor);
      if (aIndex !== bIndex) return aIndex - bIndex;
      return String(a.filename || "").localeCompare(String(b.filename || ""), "de");
    });
  }, [pdfLibraryFilter, pdfColorById, pdfs]);

  const projectRunningRun = useMemo(
    () => pdfScanRuns.find((run) => run.status === "queued" || run.status === "running") ?? null,
    [pdfScanRuns]
  );

  useEffect(() => {
    if (!previewMode && !activeRunCookieRestored) return;
    if (selectedKapitelId) return;
    if (activeRun?.kapitelIds?.[0]) {
      setSelectedKapitelId(activeRun.kapitelIds[0]);
      return;
    }
    if (kapitels.length) setSelectedKapitelId(kapitels[0]?.id ?? null);
  }, [activeRun?.kapitelIds, activeRunCookieRestored, kapitels, previewMode, selectedKapitelId]);

  useEffect(() => {
    setSelectedPdfIds((prev) => prev.filter((id) => pdfsById.has(id)));
  }, [pdfsById]);

  useEffect(() => {
    if (previewMode) return;
    setRunsLoaded(false);
    setActiveRunCookieRestored(false);
  }, [previewMode, projektId]);

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

    setOpenDocIds([]);
    setSectionRowsByDocId({});
    setSectionRowsLoaded(previewMode);
    knownDocIdsForRunRef.current = new Set();
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
    const q = query(quellenCol(firestoreClient, user.uid), where("projektId", "==", projektId), limit(500));
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((entry) => ({ id: entry.id, ...(entry.data() as QuelleDoc) }));
        setProjectQuellen(next);
      },
      (err) => {
        console.error("Failed to load Quellen for PDF color mapping:", err);
        setProjectQuellen([]);
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
        setRunsLoaded(true);
        setRuns(next);
      },
      (err) => {
        console.error("Failed to load PDF scan runs:", err);
        setRunsLoaded(true);
        setRuns([]);
      }
    );
  }, [previewMode, projektId, user?.uid]);

  useEffect(() => {
    if (previewMode) return;
    if (activeRunCookieRestored) return;
    if (!runsLoaded) return;

    const cookieRunId = String(Cookies.get(activeRunCookieKey) || "").trim();
    if (!cookieRunId) {
      setActiveRunCookieRestored(true);
      return;
    }

    const cookieRun = pdfScanRuns.find((run) => run.id === cookieRunId) ?? null;
    if (!cookieRun) {
      Cookies.remove(activeRunCookieKey);
      setActiveRunCookieRestored(true);
      return;
    }

    if (activeRunId !== cookieRun.id) {
      setActiveRunId(cookieRun.id);
    }
    const kapitelId = Array.isArray(cookieRun.kapitelIds) ? String(cookieRun.kapitelIds[0] || "").trim() : "";
    if (kapitelId && selectedKapitelId !== kapitelId) {
      setSelectedKapitelId(kapitelId);
    }
    setActiveRunCookieRestored(true);
  }, [activeRunCookieKey, activeRunCookieRestored, activeRunId, pdfScanRuns, previewMode, runsLoaded, selectedKapitelId]);

  useEffect(() => {
    if (previewMode) return;
    if (!activeRunCookieRestored) return;
    if (activeRun?.id) {
      Cookies.set(activeRunCookieKey, activeRun.id, { expires: 30, sameSite: "Lax" });
      return;
    }
    Cookies.remove(activeRunCookieKey);
  }, [activeRun?.id, activeRunCookieKey, activeRunCookieRestored, previewMode]);

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
    if (!user?.uid || !projektId || !activeRun?.id) {
      setSectionRowsByDocId({});
      setSectionRowsLoaded(false);
      return;
    }
    setSectionRowsLoaded(false);
    const q = query(quellenFinderPdfScanSectionsCol(firestoreClient, user.uid, projektId, activeRun.id), limit(5000));
    return onSnapshot(
      q,
      (snap) => {
        const rows = snap.docs
          .map((entry) => ({ id: entry.id, ...(entry.data() as PdfScanResultDoc) }))
          .sort((a, b) => {
            const scoreDiff = Number(b.score0To100 || 0) - Number(a.score0To100 || 0);
            if (scoreDiff !== 0) return scoreDiff;
            const rankDiff = Number(a.docRank || 9999) - Number(b.docRank || 9999);
            if (rankDiff !== 0) return rankDiff;
            return Number(a.pageStart || 9999) - Number(b.pageStart || 9999);
          });
        const grouped: Record<string, PdfSectionRow[]> = {};
        for (const row of rows) {
          const docId = String(row.docId || "").trim();
          if (!docId) continue;
          if (!grouped[docId]) grouped[docId] = [];
          grouped[docId]!.push(row);
        }
        setSectionRowsByDocId(grouped);
        setSectionRowsLoaded(true);
      },
      (err) => {
        console.error("Failed to load pdfScanSections:", err);
        setSectionRowsByDocId({});
        setSectionRowsLoaded(true);
      }
    );
  }, [activeRun?.id, previewMode, projektId, user?.uid]);

  useEffect(() => {
    if (!previewMode) return;
    setSectionRowsByDocId(preview?.sectionsByDocId ?? {});
    setSectionRowsLoaded(true);
  }, [previewMode, preview]);

  useEffect(() => {
    const docIds = docRows.map((row) => row.id);
    const docIdSet = new Set(docIds);
    const knownDocIds = knownDocIdsForRunRef.current;
    const newDocIds = docIds.filter((docId) => !knownDocIds.has(docId));
    for (const docId of docIds) knownDocIds.add(docId);

    setOpenDocIds((prev) => {
      const kept = prev.filter((docId) => docIdSet.has(docId));
      if (newDocIds.length === 0) return kept;
      const next = [...kept];
      for (const docId of newDocIds) {
        if (!next.includes(docId)) next.push(docId);
      }
      return next;
    });
  }, [docRows]);

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
    setOpenDocIds([]);
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

  const uploadProjectPdfs = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    if (!user?.uid || !projektId) {
      toast.error("Nicht eingeloggt", { description: "User fehlt." });
      return;
    }

    const fileList = Array.isArray(files) ? files : Array.from(files);
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
      const knownPdfs = [...pdfs];
      const skippedDuplicates: string[] = [];
      let uploadedCount = 0;

      for (let index = 0; index < fileList.length; index += 1) {
        const file = fileList[index]!;
        const originalName = String(file.name || "document.pdf").trim() || "document.pdf";
        setUploadProgress({ done: index, total: fileList.length });
        const { fileHash, pageCount } = await readPdfUploadMetadata(file);

        const duplicate = knownPdfs.find((existing) => {
          const existingHash = String(existing.fileHash || "").trim().toLowerCase();
          if (existingHash && existingHash === fileHash) return true;

          const sameName = normalizePdfFilename(existing.filename) === normalizePdfFilename(originalName);
          const sameSize = Number(existing.size || -1) === Math.max(0, Math.trunc(file.size));
          const existingPages = typeof existing.pageCount === "number" ? existing.pageCount : null;
          return sameName && sameSize && existingPages !== null && pageCount !== null && existingPages === pageCount;
        });

        if (duplicate) {
          skippedDuplicates.push(originalName);
          setUploadProgress({ done: index + 1, total: fileList.length });
          continue;
        }

        const duplicateCheck = await checkProjectPdfDuplicate({
          projektId,
          filename: originalName,
          size: Math.max(0, Math.trunc(file.size)),
          pageCount,
          fileHash,
        });
        if (duplicateCheck.duplicate) {
          skippedDuplicates.push(duplicateCheck.filename || originalName);
          setUploadProgress({ done: index + 1, total: fileList.length });
          continue;
        }

        const formData = new FormData();
        formData.set("projekt_id", projektId);
        if (pageCount !== null) formData.set("page_count", String(pageCount));
        formData.set("file", file, originalName);

        const uploadRes = await fetch("/api/quellen-finder/project-pdf-upload", {
          method: "POST",
          body: formData,
        });

        if (uploadRes.status === 409) {
          const duplicatePayload = (await uploadRes.json().catch(() => ({}))) as {
            detail?: { filename?: string | null; duplicate?: boolean } | string;
            error?: string;
          };
          const detailObj =
            typeof duplicatePayload.detail === "object" && duplicatePayload.detail !== null
              ? duplicatePayload.detail
              : null;
          skippedDuplicates.push(String(detailObj?.filename || originalName));
          setUploadProgress({ done: index + 1, total: fileList.length });
          continue;
        }

        if (!uploadRes.ok) {
          throw new Error(await readFastApiError(uploadRes));
        }

        const uploadPayload = (await uploadRes.json().catch(() => ({}))) as {
          pdf_id?: string;
          pdf?: {
            filename?: string;
            storage_path?: string;
            size?: number;
            content_type?: string;
            page_count?: number | null;
            file_hash?: string | null;
          };
        };
        const nextDoc: ProjectPdfDoc = {
          filename: String(uploadPayload.pdf?.filename || originalName),
          storagePath: String(uploadPayload.pdf?.storage_path || ""),
          size: Number.isFinite(Number(uploadPayload.pdf?.size)) ? Number(uploadPayload.pdf?.size) : Math.max(0, Math.trunc(file.size)),
          contentType: String(uploadPayload.pdf?.content_type || "application/pdf"),
          pageCount:
            typeof uploadPayload.pdf?.page_count === "number" && Number.isFinite(uploadPayload.pdf?.page_count)
              ? uploadPayload.pdf.page_count
              : pageCount,
          fileHash: String(uploadPayload.pdf?.file_hash || fileHash),
          createdAt: Timestamp.now(),
          updatedAt: Timestamp.now(),
        };
        knownPdfs.push({ id: String(uploadPayload.pdf_id || `pdf_${fileHash}`), ...nextDoc });
        uploadedCount += 1;
        setUploadProgress({ done: index + 1, total: fileList.length });
      }

      if (uploadedCount > 0) {
        toast.success("PDFs hochgeladen", { description: `${uploadedCount} Datei(en)` });
      }
      if (skippedDuplicates.length > 0) {
        toast.error("Bereits vorhandene PDFs übersprungen", {
          description: skippedDuplicates.slice(0, 3).join(", "),
        });
      }
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
    setDeletingPdfId(pdf.id);
    try {
      const url = new URL("/api/quellen-finder/project-pdf", window.location.origin);
      url.searchParams.set("projekt_id", projektId);
      url.searchParams.set("pdf_id", pdf.id);
      const res = await fetch(url.toString(), {
        method: "DELETE",
      });
      if (!res.ok) {
        toast.error("PDF löschen fehlgeschlagen", { description: await readFastApiError(res) });
        return;
      }
      setSelectedPdfIds((prev) => prev.filter((id) => id !== pdf.id));
      toast.success("PDF gelöscht", { description: pdf.filename });
    } finally {
      setDeletingPdfId((current) => (current === pdf.id ? null : current));
    }
  };

  const updateProjectPdfColor = async (pdfId: string, color: QuelleColor | null) => {
    if (!user?.uid || !projektId || previewMode) return;
    const currentPdf = pdfsById.get(pdfId);
    if (!currentPdf) return;

    const previousExplicitColor = Object.prototype.hasOwnProperty.call(currentPdf, "color")
      ? ((currentPdf.color as QuelleColor | null | undefined) ?? null)
      : undefined;
    const requestSeq = (pdfColorRequestSeqRef.current.get(pdfId) ?? 0) + 1;
    pdfColorRequestSeqRef.current.set(pdfId, requestSeq);

    setPdfs((prev) =>
      prev.map((pdf) =>
        pdf.id === pdfId
          ? {
              ...pdf,
              color,
              updatedAt: Timestamp.now(),
            }
          : pdf
      )
    );

    try {
      const res = await fetch("/api/quellen-finder/project-pdf", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projekt_id: projektId,
          pdf_id: pdfId,
          color,
        }),
      });
      if (!res.ok) {
        throw new Error(await readFastApiError(res));
      }
    } catch (err: unknown) {
      if (pdfColorRequestSeqRef.current.get(pdfId) === requestSeq) {
        setPdfs((prev) =>
          prev.map((pdf) => {
            if (pdf.id !== pdfId) return pdf;
            if (typeof previousExplicitColor === "undefined") {
              const nextPdf = { ...pdf } as PdfRow;
              delete nextPdf.color;
              return nextPdf;
            }
            return {
              ...pdf,
              color: previousExplicitColor,
              updatedAt: Timestamp.now(),
            };
          })
        );
      }
      toast.error("PDF-Farbe konnte nicht gespeichert werden", {
        description: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const requestDeleteProjectPdf = (pdf: PdfRow) => {
    if (previewMode) return;
    setDeleteConfirmPdf(pdf);
  };

  const openStoredPdf = async (pdfId: string, anchorPage?: number | null) => {
    const meta = pdfsById.get(pdfId);
    if (!meta) {
      toast.error("PDF kann nicht geöffnet werden", { description: "Kein Storage-Pfad gefunden." });
      return;
    }

    const popup = window.open("about:blank", "_blank");
    if (!popup) {
      toast.error("PDF kann nicht geöffnet werden", { description: "Popup blockiert." });
      return;
    }

    try {
      const url = new URL("/api/quellen-finder/project-pdf", window.location.origin);
      url.searchParams.set("projekt_id", projektId);
      url.searchParams.set("pdf_id", pdfId);
      const page = typeof anchorPage === "number" && Number.isFinite(anchorPage) ? `#page=${Math.max(1, Math.round(anchorPage))}` : "";
      popup.location.href = `${url.toString()}${page}`;
    } catch (err: unknown) {
      try {
        popup.close();
      } catch {
        // ignore
      }
      toast.error("PDF kann nicht geöffnet werden", { description: err instanceof Error ? err.message : String(err) });
    }
  };

  const startPdfScan = () => {
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
    setStartConfirmOpen(true);
  };

  const handleStartButtonClick = () => {
    if (selectedPdfIds.length === 0 && !previewMode && !uploading && !projectRunningRun) {
      setLibraryExpanded(true);
      setLibraryManagerOpen(true);
      return;
    }
    startPdfScan();
  };

  const confirmStartPdfScan = async () => {
    if (!selectedKapitelId || selectedPdfIds.length === 0) return;
    setStartConfirmOpen(false);
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

  const handleLibraryDragEnter = (event: DragEvent<HTMLDivElement>) => {
    if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    libraryDragDepthRef.current += 1;
    setLibraryDragActive(true);
  };

  const handleLibraryDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    if (!libraryDragActive) setLibraryDragActive(true);
  };

  const handleLibraryDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    libraryDragDepthRef.current = Math.max(0, libraryDragDepthRef.current - 1);
    if (libraryDragDepthRef.current === 0) setLibraryDragActive(false);
  };

  const handleLibraryDrop = (event: DragEvent<HTMLDivElement>) => {
    if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    libraryDragDepthRef.current = 0;
    setLibraryDragActive(false);
    const dropped = Array.from(event.dataTransfer.files || []).filter((file) => file);
    if (dropped.length > 0) void uploadProjectPdfs(dropped);
  };

  const filteredDocRows = docRows;

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
  const runCostUsd = readRunCostUsd(activeRun);
  const selectedPdfPreviewRows = selectedPdfRows.slice(0, 3);
  const hiddenSelectedPdfCount = Math.max(0, selectedPdfRows.length - selectedPdfPreviewRows.length);
  const currentStepNumber = isDone
    ? PDF_SCAN_PIPELINE_STEPS.length
    : activeStepIndex >= 0
      ? activeStepIndex + 1
      : 0;
  const currentStepLabel =
    PDF_SCAN_PIPELINE_STEPS[isDone ? PDF_SCAN_PIPELINE_STEPS.length - 1 : Math.max(0, activeStepIndex)]?.label ?? "Pipeline";
  const runOutcomeLabel = isDone ? "Erfolgreich" : isCancelled ? "Abgebrochen" : isError ? "Fehler" : "Läuft";

  const startDisabledReasons: string[] = [];
  if (previewMode) startDisabledReasons.push("Der Scan ist in dieser Vorschau deaktiviert.");
  if (!selectedKapitelId) startDisabledReasons.push("Wähle zuerst ein Kapitel aus.");
  if (selectedPdfIds.length === 0) startDisabledReasons.push("Wähle mindestens eine PDF aus der Bibliothek aus.");
  if (uploading) startDisabledReasons.push("Warte, bis der aktuelle PDF-Upload abgeschlossen ist.");
  if (projectRunningRun) startDisabledReasons.push("In diesem Projekt läuft bereits ein anderer PDF-Scan.");
  const canStart = startDisabledReasons.length === 0;
  const canOpenLibraryFromStart = !previewMode && !uploading && !projectRunningRun && selectedPdfIds.length === 0;
  const startButtonEnabled = canStart || canOpenLibraryFromStart;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f7f8fb] text-slate-900">
      <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-4">
          <Button asChild variant="ghost" size="icon">
            <Link href="/dashboard" aria-label="Back to dashboard">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div className="min-w-0">
            <div className="truncate text-lg font-semibold text-slate-950">PDF-Scan</div>
            <div className="truncate text-sm text-slate-500">PDFs nach relevanten Inhalten für Kapitel durchsuchen</div>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <aside className="flex min-h-0 w-[340px] shrink-0 flex-col overflow-hidden border-r border-slate-200 bg-white">
          <div className="shrink-0 space-y-4 border-b border-slate-200 px-5 py-5">
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-600">Kapitel auswählen</div>
              <Select value={selectedKapitelId || ""} onValueChange={(value) => selectKapitel(value || null)}>
                <SelectTrigger className="h-auto min-h-10 w-full rounded-[4px] items-center whitespace-normal border-slate-200 bg-white px-3 py-2.5 shadow-none">
                  <div className="min-w-0 flex-1 text-left">
                    {selectedKapitel ? (
                      <div className="line-clamp-1 text-[14px] leading-snug">
                        <span className="mr-2 text-slate-400 tabular-nums">{selectedKapitel.nummer}</span>
                        {selectedKapitel.title}
                      </div>
                    ) : (
                      <span className="text-slate-400">Kapitel wählen...</span>
                    )}
                  </div>
                </SelectTrigger>
                <SelectContent align="start" className="max-h-[60vh] w-[var(--radix-select-trigger-width)]">
                  {kapitels.map((kapitel) => {
                    const depth = kapitelDepth(kapitel.nummer);
                    return (
                      <SelectItem key={kapitel.id} value={kapitel.id}>
                        <div className="flex min-w-0 w-full items-start gap-2" style={{ paddingLeft: depth * 12 }}>
                          <span className="shrink-0 text-slate-400 tabular-nums">{kapitel.nummer}</span>
                          <span className="min-w-0 leading-snug line-clamp-2">{kapitel.title}</span>
                        </div>
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>

            <div>
              <button
                type="button"
                onClick={() => setLibraryExpanded((current) => !current)}
                className="flex w-full items-center justify-between gap-3 text-left"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <FolderOpen className="h-4 w-4 text-slate-500" />
                  <span className="text-sm font-medium text-slate-700">PDF-Bibliothek</span>
                  <Badge variant="outline" className="border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-700">
                    {formatIntDe(selectedPdfIds.length)} ausgewählt
                  </Badge>
                </div>
                {libraryExpanded ? <ChevronUp className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
              </button>

              {libraryExpanded ? (
                <div className="mt-3 rounded-[14px] border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-[18px] font-semibold leading-none tracking-[-0.03em] text-slate-950">{formatIntDe(pdfs.length)}</div>
                      <div className="mt-2 text-[14px] font-medium text-slate-900">PDFs verfügbar</div>
                      <div className="mt-1 text-[14px] leading-6 text-slate-500">{formatIntDe(selectedPdfIds.length)} für Scan ausgewählt</div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-10 rounded-[4px] border-slate-200 bg-white px-4 text-sm shadow-none"
                      onClick={() => setLibraryManagerOpen(true)}
                    >
                      Verwalten
                    </Button>
                  </div>

                  <div className="mt-5 border-t border-slate-200 pt-5">
                    <div className="text-[13px] font-medium text-slate-500">Ausgewählte PDFs:</div>
                    {selectedPdfPreviewRows.length === 0 ? (
                      <div className="mt-3 text-sm leading-6 text-slate-500">Noch keine PDFs ausgewählt.</div>
                    ) : (
                      <TooltipProvider delayDuration={120}>
                        <div className="mt-3 space-y-2.5">
                        {selectedPdfPreviewRows.map((pdf) => (
                          <div key={pdf.id} className="flex items-start gap-2.5">
                            <FileText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="min-w-0 flex-1 truncate text-sm text-slate-900">
                                  {pdf.filename}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent side="right" className="max-w-[360px] break-all text-xs">
                                {pdf.filename}
                              </TooltipContent>
                            </Tooltip>
                            <button
                              type="button"
                              className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center text-slate-400 transition-colors hover:text-slate-700"
                              onClick={() => togglePdfSelection(pdf.id, false)}
                              title="Aus Auswahl entfernen"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                        {hiddenSelectedPdfCount > 0 ? (
                          <button
                            type="button"
                            className="text-sm text-sky-700 transition-colors hover:text-sky-800"
                            onClick={() => setLibraryManagerOpen(true)}
                          >
                            +{formatIntDe(hiddenSelectedPdfCount)} weitere...
                          </button>
                        ) : null}
                        </div>
                      </TooltipProvider>
                    )}
                  </div>
                </div>
              ) : null}
            </div>

            <div>
              {startButtonEnabled ? (
                <Button
                  size="lg"
                  onClick={handleStartButtonClick}
                  className="h-10 w-full rounded-[4px] bg-[#1680cd] px-4 text-[15px] font-medium shadow-none hover:bg-[#0f76c2]"
                >
                  {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                  Scan starten{selectedPdfIds.length > 0 ? ` (${formatIntDe(selectedPdfIds.length)} PDFs)` : ""}
                </Button>
              ) : (
                <TooltipProvider delayDuration={120}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="block w-full">
                        <Button
                          size="lg"
                          disabled
                          className="h-10 w-full rounded-[4px] bg-[#1680cd] px-4 text-[15px] font-medium shadow-none hover:bg-[#0f76c2]"
                        >
                          {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                          Scan starten{selectedPdfIds.length > 0 ? ` (${formatIntDe(selectedPdfIds.length)} PDFs)` : ""}
                        </Button>
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-[320px] text-xs leading-5">
                      <div className="space-y-1">
                        {startDisabledReasons.map((reason) => (
                          <div key={reason}>{reason}</div>
                        ))}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              )}
              {projectRunningRun && projectRunningRun.id !== activeRun?.id ? (
                <div className="mt-3 text-xs leading-5 text-slate-500">
                  Es läuft bereits ein anderer Scan im Projekt. Wähle ihn unten aus, um den Status zu verfolgen.
                </div>
              ) : null}
            </div>
          </div>

          <div className="flex-1 overflow-auto border-t border-slate-200">
            <div className="px-5 py-4 text-sm font-semibold text-slate-800">Runs</div>
            <div className="divide-y divide-slate-200">
              {pdfScanRuns.length === 0 ? (
                <div className="px-5 py-14 text-center">
                  <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
                    <FileText className="h-6 w-6 text-slate-400" />
                  </div>
                  <div className="mt-4 text-base font-medium text-slate-800">Noch keine Scans</div>
                  <div className="mt-2 text-sm leading-6 text-slate-500">Wähle Kapitel und PDFs aus, um zu starten.</div>
                </div>
              ) : (
                pdfScanRuns.map((run) => {
                  const snapshot = run.kapitelSnapshots?.[0] ?? null;
                  const label = `${snapshot?.nummer ? `${snapshot.nummer} ` : ""}${snapshot?.title || run.id}`.trim();
                  const subtitle =
                    run.status === "queued" || run.status === "running"
                      ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  Läuft...`
                      : run.status === "success"
                        ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  ${formatIntDe(run.pdfScanDocCount ?? 0)} PDFs · ${formatIntDe(run.usefulPdfCount ?? run.pdfScanSectionCount ?? 0)} nützlich`
                        : run.status === "cancelled"
                          ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  Abgebrochen`
                          : `${formatTimeHm(run.startedAt ?? run.createdAt)}  Fehler`;
                  const active = run.id === activeRun?.id;
                  const icon =
                    run.status === "queued" || run.status === "running" ? (
                      <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
                    ) : run.status === "success" ? (
                      <Check className="h-4 w-4 text-sky-600" />
                    ) : run.status === "cancelled" ? (
                      <Ban className="h-4 w-4 text-slate-400" />
                    ) : (
                      <AlertTriangle className="h-4 w-4 text-rose-500" />
                    );

                  return (
                    <button
                      key={run.id}
                      type="button"
                      onClick={() => selectRun(run)}
                      className={cn(
                        "w-full px-5 py-3.5 text-left transition-colors hover:bg-slate-50",
                        active && "bg-sky-50/70"
                      )}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-slate-900">{label}</div>
                          <div className="mt-1 truncate text-xs text-slate-500">{subtitle}</div>
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

        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className={cn("flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden px-5 py-4", activeRun ? "gap-4" : "")}>
              {activeRun ? (
                <>
                  <div className="shrink-0 space-y-4">
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0">
                      <div className="text-[18px] font-semibold tracking-[-0.02em] text-slate-950">{chapterHeading}</div>
                      <div className="mt-1 text-xs text-slate-500">
                        Gestartet: {formatDateTimeWithSeconds(runStartedAt)}
                        {runFinishedAt ? <> · Abgeschlossen: {formatDateTimeWithSeconds(runFinishedAt)}</> : null}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 xl:justify-end">
                      {running ? (
                        <>
                          <div className="inline-flex items-center gap-1.5">
                            <Clock3 className="h-3.5 w-3.5" />
                            <span className="tabular-nums">{formatElapsedShort(elapsedMs)}</span>
                          </div>
                          <span className="text-slate-300">|</span>
                          <div className="inline-flex items-center gap-1.5">
                            <span>Phase:</span>
                            <span className="tabular-nums">{formatElapsedShort(stageElapsedMs)}</span>
                          </div>
                        </>
                      ) : null}
                      {runCostUsd !== null ? (
                        <>
                          {running ? <span className="text-slate-300">|</span> : null}
                          <div className="inline-flex items-center gap-1.5">
                            <DollarSign className="h-3.5 w-3.5" />
                            <span className="tabular-nums">{formatUsd(runCostUsd)}</span>
                          </div>
                        </>
                      ) : null}
                      {running ? (
                        <Button size="sm" variant="outline" className="h-8 rounded-[4px] border-slate-200 bg-white px-3 text-xs shadow-none" onClick={cancelPdfScan} disabled={isCancelRequested}>
                          {isCancelRequested ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <X className="mr-2 h-3.5 w-3.5" />}
                          {isCancelRequested ? "Wird abgebrochen..." : "Abbrechen"}
                        </Button>
                      ) : null}
                    </div>
                  </div>

                  <Card className="rounded-[14px] border border-slate-200 bg-white shadow-sm">
                    <div className="p-4">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0">
                          <div className="text-[14px] font-semibold tracking-[-0.01em] text-slate-950">Pipeline-Status</div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <span className="tabular-nums">
                            {formatIntDe(currentStepNumber)} / {formatIntDe(PDF_SCAN_PIPELINE_STEPS.length)} Schritte
                          </span>
                        </div>
                      </div>

                      <div className="mt-4">
                        <div className="overflow-hidden rounded-full bg-slate-100">
                          <TooltipProvider delayDuration={120}>
                            <div className="flex">
                              {PDF_SCAN_PIPELINE_STEPS.map((step, index) => {
                                const stageSnapshot = readPipelineStage(activeRun, step.key);
                                const snapshotStatus = String(stageSnapshot?.status || "").trim();
                                const isStageCompleted =
                                  snapshotStatus === "completed" || (!snapshotStatus && (isDone || index < activeStepIndex));
                                const isStageActive =
                                  snapshotStatus === "running" || (!snapshotStatus && running && activeStepIndex === index);
                                const isStageError = snapshotStatus === "error";
                                const isStageCancelled = snapshotStatus === "cancelled";
                                const fillWidth = isStageCompleted || isStageError || isStageCancelled || isStageActive ? 100 : 0;
                                const fillClass = isStageCancelled
                                  ? "bg-slate-400"
                                  : isStageError
                                    ? "bg-rose-500"
                                    : isStageCompleted
                                      ? "bg-[#1680cd]"
                                      : isStageActive
                                        ? "bg-[#f59e0b] animate-[pulse_1.25s_ease-in-out_infinite]"
                                        : "bg-transparent";
                                const durationMs =
                                  typeof stageSnapshot?.elapsedMs === "number"
                                    ? stageSnapshot.elapsedMs
                                    : isStageActive && stageKey === step.key
                                      ? stageElapsedMs
                                      : null;
                                const stageCurrent =
                                  typeof stageSnapshot?.current === "number"
                                    ? stageSnapshot.current
                                    : isStageActive && typeof activeRun?.progress?.current === "number"
                                      ? activeRun.progress.current
                                      : null;
                                const stageTotal =
                                  typeof stageSnapshot?.total === "number"
                                    ? stageSnapshot.total
                                    : isStageActive && typeof activeRun?.progress?.total === "number"
                                      ? activeRun.progress.total
                                      : null;

                                return (
                                  <Tooltip key={step.key}>
                                    <TooltipTrigger asChild>
                                      <div
                                        className={cn(
                                          "relative h-[7px] flex-1 cursor-default overflow-hidden bg-slate-100",
                                          index < PDF_SCAN_PIPELINE_STEPS.length - 1 ? "border-r border-white/80" : ""
                                        )}
                                        aria-label={`${step.title}: ${step.description}`}
                                      >
                                        <div className={cn("absolute inset-y-0 left-0", fillClass)} style={{ width: `${Math.max(0, Math.min(100, fillWidth))}%` }} />
                                      </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="top" className="max-w-[240px] rounded-[8px] px-3 py-2 text-left">
                                      <div className="text-[12px] font-semibold text-white">{step.title}</div>
                                      <div className="mt-0.5 text-[11px] leading-5 text-slate-200">{step.description}</div>
                                      {durationMs !== null ? (
                                        <div className="mt-2 text-[11px] tabular-nums text-slate-300">
                                          {isStageCompleted || isStageError || isStageCancelled ? `Dauer: ${formatElapsedShort(durationMs)}` : `Läuft seit: ${formatElapsedShort(durationMs)}`}
                                        </div>
                                      ) : null}
                                      {typeof stageCurrent === "number" && typeof stageTotal === "number" && stageTotal > 0 ? (
                                        <div className="mt-1 text-[11px] tabular-nums text-slate-300">
                                          {formatIntDe(stageCurrent)}/{formatIntDe(stageTotal)}
                                        </div>
                                      ) : null}
                                    </TooltipContent>
                                  </Tooltip>
                                );
                              })}
                            </div>
                          </TooltipProvider>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs">
                          <div className="flex items-center gap-2 text-slate-600">
                            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" /> : isDone ? <Check className="h-3.5 w-3.5 text-sky-600" /> : null}
                            <span>
                              {isDone ? "Abgeschlossen" : isCancelled ? "Abgebrochen" : isError ? "Fehlgeschlagen" : `${currentStepLabel}: ${stageLabel(activeRun)}`}
                            </span>
                          </div>
                          <div className="tabular-nums text-slate-500">
                            {formatIntDe(currentStepNumber)}/{formatIntDe(PDF_SCAN_PIPELINE_STEPS.length)}
                          </div>
                        </div>
                      </div>

                      {isError ? (
                        <div className="mt-4 rounded-[12px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                          {String(activeRun.errorMessage || "").trim() || "Unbekannter Fehler"}
                        </div>
                      ) : null}
                    </div>
                  </Card>

                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <Card className="rounded-[14px] border border-slate-200 bg-white px-4 py-3.5 shadow-sm">
                      <div className="text-[13px] text-slate-500">Status</div>
                      <div
                        className={cn(
                          "mt-4.5 text-[16px] font-semibold tracking-[-0.02em]",
                          isError ? "text-rose-600" : isCancelled ? "text-slate-500" : running ? "text-amber-600" : "text-sky-700"
                        )}
                      >
                        {runOutcomeLabel}
                      </div>
                    </Card>
                    <Card className="rounded-[14px] border border-slate-200 bg-white px-4 py-3.5 shadow-sm">
                      <div className="text-[13px] text-slate-500">PDFs</div>
                      <div className="mt-4.5 text-[16px] font-semibold tracking-[-0.02em] text-slate-950">{formatIntDe(visibleDocCount)}</div>
                    </Card>
                    <Card className="rounded-[14px] border border-slate-200 bg-white px-4 py-3.5 shadow-sm">
                      <div className="text-[13px] text-slate-500">Abschnitte</div>
                      <div className="mt-4.5 text-[16px] font-semibold tracking-[-0.02em] text-slate-950">{formatIntDe(visibleSectionCount)}</div>
                    </Card>
                    <Card className="rounded-[14px] border border-slate-200 bg-white px-4 py-3.5 shadow-sm">
                      <div className="text-[13px] text-slate-500">Nützlich</div>
                      <div className="mt-4.5 text-[16px] font-semibold tracking-[-0.02em] text-slate-950">{formatIntDe(usefulPdfCount)}</div>
                    </Card>
                  </div>
                  </div>
                </>
              ) : null}

              {!activeRun ? (
                <MainEmptyState selectedKapitel={selectedKapitel} />
              ) : (
                <div className="space-y-5 pb-4 pt-2">
                  <div className="min-w-0">
                    <div className="text-[14px] font-semibold tracking-[-0.01em] text-slate-950">Ergebnisse</div>
                  </div>

                  <div className="pt-0">
                  {!docRowsLoaded ? (
                    <ResultSkeleton />
                  ) : filteredDocRows.length === 0 ? (
                    <Card className="rounded-[14px] border border-dashed border-slate-200 bg-white px-5 py-14 text-center shadow-none">
                      <div className="text-base font-medium text-slate-900">
                        {running ? "Noch keine finalen Ergebnisse" : "Keine sichtbaren Sections"}
                      </div>
                      <div className="mt-2 text-sm leading-7 text-slate-500">
                        {running
                          ? "Die Ergebnisse erscheinen nach Phase G und dem Persistieren der finalen Section-Scores."
                          : "Für diesen Lauf wurden keine finalen Sections gespeichert."}
                      </div>
                    </Card>
                  ) : (
                    <Accordion
                      type="multiple"
                      value={openDocIds}
                      onValueChange={(value) => setOpenDocIds(value)}
                      className="space-y-4"
                    >
                      {filteredDocRows.map((pdfDoc) => {
                        const pdfMeta = pdfsById.get(String(pdfDoc.pdfId || ""));
                        const topScore = typeof pdfDoc.topSectionScore === "number" ? pdfDoc.topSectionScore : null;
                        const isOpen = openDocIds.includes(pdfDoc.id);
                        const sectionRows = sectionRowsByDocId[pdfDoc.id] ?? [];

                        return (
                          <AccordionItem
                            key={pdfDoc.id}
                            value={pdfDoc.id}
                            className="overflow-hidden rounded-[14px] border border-slate-200/90 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]"
                          >
                            <AccordionTrigger className="items-center px-6 py-8 hover:no-underline [&>svg]:hidden">
                              <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_72px] items-center gap-5 text-left">
                                <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-4.5">
                                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-400">
                                    <FileText className="h-4 w-4" />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <div
                                      className="block w-full truncate pr-4 text-[14px] font-medium leading-6 text-slate-950"
                                      title={pdfDoc.docTitle || pdfDoc.pdfLabel || "Unbenanntes PDF"}
                                    >
                                      {pdfDoc.docTitle || pdfDoc.pdfLabel || "Unbenanntes PDF"}
                                    </div>
                                    <div className="mt-1.5 text-[13px] leading-5 text-slate-500">
                                      {typeof pdfDoc.pageCount === "number" ? `${formatIntDe(pdfDoc.pageCount)} Seiten` : "PDF"}
                                      {typeof pdfDoc.visibleSectionCount === "number" ? ` · ${formatIntDe(pdfDoc.visibleSectionCount)} Abschnitte` : ""}
                                    </div>
                                  </div>
                                </div>

                                <div className="flex h-full w-[72px] shrink-0 items-center justify-end gap-2 text-right">
                                  <div className="text-[15px] font-semibold leading-none tabular-nums text-sky-700">
                                    {topScore !== null ? formatScore(topScore, 1) : "—"}
                                  </div>
                                  <ChevronDown
                                    className={cn(
                                      "h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200",
                                      isOpen ? "rotate-180" : ""
                                    )}
                                  />
                                </div>
                              </div>
                            </AccordionTrigger>

                            <AccordionContent className="bg-white pb-0">
                              {!isOpen || !sectionRowsLoaded ? (
                                <div className="space-y-3 border-t border-slate-100 px-5 pb-6 pt-4">
                                  {isOpen
                                    ? Array.from({ length: 2 }).map((_, idx) => (
                                        <Card key={idx} className="rounded-[14px] border border-slate-200 bg-white p-4 shadow-none">
                                          <Skeleton className="h-5 w-2/3" />
                                          <Skeleton className="mt-3 h-4 w-1/2" />
                                        </Card>
                                      ))
                                    : null}
                                </div>
                              ) : sectionRows.length === 0 ? (
                                <div className="border-t border-slate-100 px-5 pb-6 pt-4">
                                  <div className="rounded-[14px] border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                                    Für dieses PDF wurden keine finalen Sections geladen.
                                  </div>
                                </div>
                              ) : (
                                <div className="border-t border-slate-100 bg-white pb-5">
                                  <div className="divide-y divide-slate-100">
                                  {sectionRows.map((section) => {
                                    const sectionScore = typeof section.score0To100 === "number" ? section.score0To100 : null;
                                    return (
                                      <div key={section.id} className="px-5 py-[15px]">
                                        <div className="flex items-center justify-between gap-4">
                                          <div className="flex min-w-0 items-center gap-4">
                                            <div className="shrink-0">
                                              <div className="inline-flex min-w-[40px] items-center justify-center rounded-[4px] border border-sky-400 bg-white px-2.5 py-0.5 text-[12px] font-semibold leading-none tabular-nums text-sky-700">
                                                {sectionScore !== null ? formatScore(sectionScore, 1) : "—"}
                                              </div>
                                            </div>
                                            <div className="min-w-0">
                                              <div
                                                className="truncate text-[14px] font-medium leading-6 text-slate-950"
                                                title={section.title || section.sectionPathText || "Untitled section"}
                                              >
                                                {section.title || section.sectionPathText || "Untitled section"}
                                              </div>
                                              <div className="mt-1.5 flex flex-wrap items-center gap-2.5 text-[13px] leading-5 text-slate-500">
                                                <span>{formatPageRange(section.pageStart, section.pageEnd)}</span>
                                                {(section.subpointCoverageIds || []).slice(0, 6).map((subpointId) => (
                                                  <Badge key={`${section.id}_${subpointId}`} variant="outline" className="rounded-[4px] border-slate-200 bg-slate-50 px-1.5 py-0 text-[11px] text-slate-600">
                                                    {subpointId}
                                                  </Badge>
                                                ))}
                                              </div>
                                            </div>
                                          </div>

                                          <div className="shrink-0">
                                            <Button
                                              size="icon"
                                              variant="ghost"
                                              className="h-8 w-8 rounded-[6px] text-slate-500 shadow-none hover:bg-slate-50 hover:text-slate-900"
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
                                              title="Preview"
                                            >
                                              <Eye className="h-4 w-4" />
                                            </Button>
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                  </div>
                                </div>
                              )}
                            </AccordionContent>
                          </AccordionItem>
                        );
                      })}
                    </Accordion>
                  )}
                  </div>
                </div>
              )}
            </div>
          </main>
        </div>

        <Dialog
          open={libraryManagerOpen}
          onOpenChange={(open) => {
            setLibraryManagerOpen(open);
            if (!open) {
              libraryDragDepthRef.current = 0;
              setLibraryDragActive(false);
            }
          }}
        >
          <DialogContent
            className="max-h-[86vh] max-w-[1024px] gap-0 overflow-hidden border-slate-200 bg-white p-0 shadow-[0_24px_80px_rgba(15,23,42,0.24)] sm:max-w-[1024px]"
            onDragEnter={handleLibraryDragEnter}
            onDragOver={handleLibraryDragOver}
            onDragLeave={handleLibraryDragLeave}
            onDrop={handleLibraryDrop}
          >
            <DialogHeader className="border-b border-slate-200 bg-white px-6 py-5">
              <DialogTitle className="text-[20px] tracking-[-0.02em] text-slate-950">PDF-Bibliothek verwalten</DialogTitle>
              <DialogDescription className="sr-only">
                Verwalte die PDF-Bibliothek dieses Projekts, suche nach vorhandenen PDFs, wähle Dateien für den Scan aus,
                ändere Farben, öffne PDFs oder lade neue PDFs hoch.
              </DialogDescription>
            </DialogHeader>

            <div className="border-b border-slate-200 bg-slate-50 px-6 py-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <Input
                    value={pdfLibraryFilter}
                    onChange={(event) => setPdfLibraryFilter(event.target.value)}
                    placeholder="PDFs durchsuchen..."
                    className="h-11 border-slate-200 bg-white pl-10 shadow-none"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-10 border-slate-200 bg-white px-4 shadow-none"
                    onClick={() => setVisibleSelection(true)}
                  >
                    Alle wählen
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-10 border-slate-200 bg-white px-4 shadow-none"
                    onClick={() => setVisibleSelection(false)}
                  >
                    Keine
                  </Button>
                  <Button
                    size="sm"
                    className="h-10 bg-[#1680cd] px-4 shadow-none hover:bg-[#0f76c2]"
                    disabled={uploading || previewMode}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {uploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileUp className="mr-2 h-4 w-4" />}
                    Upload
                  </Button>
                </div>
              </div>

              {uploadProgress ? (
                <div className="mt-3 rounded-[14px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  Upload läuft: {formatIntDe(uploadProgress.done)} / {formatIntDe(uploadProgress.total)}
                </div>
              ) : null}

              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf,.pdf"
                multiple
                className="hidden"
                onChange={(event) => void uploadProjectPdfs(event.target.files)}
              />
            </div>

            <ScrollArea className="h-[min(62vh,640px)] bg-white">
              <div className="divide-y divide-slate-200">
                {pdfs.length === 0 ? (
                  <div className="px-6 py-12 text-center text-sm text-slate-500">Noch keine PDFs hochgeladen.</div>
                ) : filteredPdfs.length === 0 ? (
                  <div className="px-6 py-12 text-center text-sm text-slate-500">Keine PDFs passen zum aktuellen Filter.</div>
                ) : (
                  filteredPdfs.map((pdf) => {
                    const isSelected = selectedPdfIdSet.has(pdf.id);
                    const isDeleting = deletingPdfId === pdf.id;
                    const pdfColor = pdfColorById.get(pdf.id) ?? null;
                    return (
                      <div
                        key={pdf.id}
                        className={cn(
                          "grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 bg-white px-6 py-4 transition-colors",
                          isSelected ? "border-l-2 border-l-sky-500 bg-[#edf6fd] pl-[22px]" : "hover:bg-white"
                        )}
                      >
                        <Checkbox
                          checked={isSelected}
                          onCheckedChange={(checked) => togglePdfSelection(pdf.id, Boolean(checked))}
                          aria-label={`${pdf.filename} auswählen`}
                        />

                        <div className="flex min-w-0 items-center gap-3.5">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                type="button"
                                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-transform hover:scale-110"
                                style={{
                                  backgroundColor: pdfColor ? colorMap[pdfColor] : "#FFFFFF",
                                  borderColor: pdfColor ? colorMap[pdfColor] : "#CBD5E1",
                                }}
                                disabled={previewMode}
                                aria-label={`Farbe für ${pdf.filename} auswählen`}
                                onClick={(event) => event.stopPropagation()}
                              />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="start"
                              sideOffset={8}
                              className="flex items-center gap-1.5 rounded-[10px] border border-slate-200 bg-white p-1.5 shadow-[0_10px_24px_rgba(15,23,42,0.10)]"
                            >
                              {PDF_LIBRARY_COLOR_PICKER_ORDER.map((color) => {
                                const swatchColor = color ? colorMap[color] : "#FFFFFF";
                                const ringColor = color ? colorMap[color] : "#CBD5E1";
                                const isActive = pdfColor === color;
                                return (
                                  <DropdownMenuItem
                                    key={color ?? "none"}
                                    className="flex h-8 w-8 min-h-0 min-w-0 cursor-pointer items-center justify-center rounded-full p-0 focus:bg-transparent data-[highlighted]:bg-transparent"
                                    onSelect={() => void updateProjectPdfColor(pdf.id, color)}
                                    title={color ?? "Keine Farbe"}
                                  >
                                    <span
                                      className="block h-6 w-6 rounded-full border border-white"
                                      style={{
                                        backgroundColor: swatchColor,
                                        boxShadow: isActive
                                          ? `0 0 0 2px ${ringColor}`
                                          : color
                                            ? "none"
                                            : "inset 0 0 0 1px #CBD5E1",
                                      }}
                                    />
                                  </DropdownMenuItem>
                                );
                              })}
                            </DropdownMenuContent>
                          </DropdownMenu>
                          <button
                            type="button"
                            onClick={() => togglePdfSelection(pdf.id, !isSelected)}
                            className="flex min-w-0 items-center gap-3.5 text-left"
                          >
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-400">
                              <FileText className="h-4.5 w-4.5" />
                            </div>
                            <div className="min-w-0">
                              <div className="truncate text-[14px] font-medium text-slate-950" title={pdf.filename}>
                                {pdf.filename}
                              </div>
                              <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-slate-500">
                                {typeof pdf.pageCount === "number" ? (
                                  <span className="inline-flex items-center gap-1.5">
                                    <BookOpen className="h-3.5 w-3.5" />
                                    {formatIntDe(pdf.pageCount)} Seiten
                                  </span>
                                ) : null}
                                <span className="inline-flex items-center gap-1.5">
                                  <HardDrive className="h-3.5 w-3.5" />
                                  {formatBytes(pdf.size)}
                                </span>
                                <span className="inline-flex items-center gap-1.5">
                                  <CalendarDays className="h-3.5 w-3.5" />
                                  {formatDateShort(pdf.createdAt)}
                                </span>
                              </div>
                            </div>
                          </button>
                        </div>

                        <div className="flex items-center gap-1">
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-9 w-9 text-slate-500 hover:text-slate-900"
                            onClick={() => void openStoredPdf(pdf.id)}
                            title="PDF öffnen"
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-9 w-9 text-rose-500 hover:text-rose-600"
                            disabled={isDeleting || previewMode}
                            onClick={() => requestDeleteProjectPdf(pdf)}
                            title="PDF löschen"
                          >
                            {isDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                          </Button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </ScrollArea>

            <DialogFooter className="border-t border-slate-200 bg-slate-50 px-6 py-4 sm:items-center sm:justify-between">
              <div className="text-sm text-slate-500">
                {formatIntDe(selectedPdfIds.length)} von {formatIntDe(pdfs.length)} ausgewählt
              </div>
              <Button className="bg-[#1680cd] shadow-none hover:bg-[#0f76c2]" onClick={() => setLibraryManagerOpen(false)}>
                Fertig
              </Button>
            </DialogFooter>

            {libraryDragActive ? (
              <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-sky-950/8 p-6">
                <div className="rounded-[18px] border-2 border-dashed border-sky-400 bg-white/96 px-10 py-10 text-center shadow-xl">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-sky-50 text-sky-700">
                    <FileUp className="h-6 w-6" />
                  </div>
                  <div className="mt-4 text-lg font-semibold text-slate-950">PDFs hier ablegen</div>
                  <div className="mt-2 text-sm text-slate-500">Die Dateien werden direkt in die Projektbibliothek hochgeladen.</div>
                </div>
              </div>
            ) : null}
          </DialogContent>
        </Dialog>

        <AlertDialog open={startConfirmOpen} onOpenChange={setStartConfirmOpen}>
          <AlertDialogContent className="max-w-[520px] rounded-[14px] border-slate-200 shadow-xl">
            <AlertDialogHeader>
              <AlertDialogTitle>PDF-Scan starten?</AlertDialogTitle>
              <AlertDialogDescription className="text-left text-sm leading-6 text-slate-600">
                <span className="block">Der Scan wird als neuer Lauf gestartet.</span>
                <span className="mt-2 block">
                  Kapitel: <span className="font-medium text-slate-900">{chapterHeading}</span>
                </span>
                <span className="block">
                  PDFs: <span className="font-medium text-slate-900">{formatIntDe(selectedPdfIds.length)}</span>
                </span>
                <span className="mt-3 block">
                  Die Verarbeitung kann je nach Anzahl und Grösse der PDFs bis zu eine Stunde oder länger dauern.
                </span>
                <span className="block">Der Fortschritt wird live im Pipeline-Status angezeigt und der Lauf kann bei Bedarf abgebrochen werden.</span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel className="rounded-[4px]">Abbrechen</AlertDialogCancel>
              <AlertDialogAction
                className="rounded-[4px] border-[#1680cd] bg-[#1680cd] text-white hover:bg-[#0f76c2]"
                onClick={() => void confirmStartPdfScan()}
              >
                Scan starten
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <AlertDialog open={Boolean(deleteConfirmPdf)} onOpenChange={(open) => (!open ? setDeleteConfirmPdf(null) : null)}>
          <AlertDialogContent className="max-w-[520px] rounded-[14px] border-slate-200 shadow-xl">
            <AlertDialogHeader>
              <AlertDialogTitle>PDF löschen?</AlertDialogTitle>
              <AlertDialogDescription className="text-left text-sm leading-6 text-slate-600">
                <span className="block">Diese PDF wird aus der Projektbibliothek entfernt.</span>
                <span className="mt-2 block font-medium text-slate-900">{deleteConfirmPdf?.filename || "Unbenannte PDF"}</span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel className="rounded-[4px]">Abbrechen</AlertDialogCancel>
              <AlertDialogAction
                className="rounded-[4px]"
                onClick={() => {
                  const pdf = deleteConfirmPdf;
                  setDeleteConfirmPdf(null);
                  if (pdf) void deleteProjectPdf(pdf);
                }}
              >
                PDF löschen
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <PdfExtractDialog open={extractOpen} onOpenChange={setExtractOpen} request={extractRequest} />
      </div>
  );
}
