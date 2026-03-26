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
  quellenFinderPdfScanChapterDocsCol,
  quellenFinderPdfScanChapterSectionsCol,
  quellenFinderPdfScanChaptersCol,
} from "@/app/lib/firestore/refs";
import type {
  PdfScanChapterDoc,
  PdfScanChapterDocSummaryDoc,
  PdfScanChapterSectionDoc,
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
type ChapterRow = WithId<PdfScanChapterDoc>;
type PdfDocRow = WithId<PdfScanChapterDocSummaryDoc>;
type PdfSectionRow = WithId<PdfScanChapterSectionDoc>;
type QuelleRow = WithId<QuelleDoc>;
type ToDateLike = { toDate: () => Date };
type PdfJsModule = typeof import("pdfjs-dist");
export type PdfScanWorkspacePreview = {
  pdfs: PdfRow[];
  runs: RunRow[];
  docRows: PdfDocRow[];
  sectionsByDocId: Record<string, PdfSectionRow[]>;
  chapterRows?: ChapterRow[];
  initialSelectedKapitelId?: string | null;
  initialSelectedKapitelIds?: string[];
  initialSelectedPdfIds?: string[];
  initialActiveRunId?: string | null;
  initialActiveChapterId?: string | null;
  initialActiveDocId?: string | null;
  initialLibraryManagerOpen?: boolean;
};

const PDF_SCAN_PIPELINE_STEPS: Array<{ key: string; label: string; title: string; description: string }> = [
  { key: "prepare_inputs", label: "Inputs", title: "Inputs", description: "Prepare run inputs" },
  { key: "download_pdfs", label: "Download", title: "Download", description: "Download selected PDFs" },
  { key: "phase_a", label: "Phase A", title: "Phase A", description: "Build pipeline manifest" },
  { key: "phase_b", label: "Phase B", title: "Phase B", description: "Text extraction" },
  { key: "phase_c", label: "Phase C", title: "Phase C", description: "Normalize sections" },
  { key: "phase_c5", label: "Phase C.5", title: "Phase C.5", description: "Prepare shared retrieval cache" },
  { key: "phase_d", label: "Phase D", title: "Phase D", description: "Plan retrieval" },
  { key: "phase_e", label: "Phase E", title: "Phase E", description: "Retrieve candidates" },
  { key: "phase_f", label: "Phase F", title: "Phase F", description: "Rerank candidates" },
  { key: "phase_g", label: "Phase G", title: "Phase G", description: "Score final sections" },
  { key: "phase_h", label: "Phase H", title: "Phase H", description: "Aggregate chapter results" },
  { key: "persist_results", label: "Persist", title: "Persist", description: "Save UI results" },
];

const PDF_LIBRARY_COLOR_PICKER_ORDER: Array<QuelleColor | null> = [null, "rose", "peach", "cream", "green", "teal", "blue", "lavender"];
const PDF_SCAN_MAX_PDFS_PER_RUN = 30;
const PDF_UPLOAD_MAX_BYTES = 100 * 1024 * 1024;

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

function buildPdfScanRunLabel(run: RunRow): string {
  const explicit = String(run.pdfScanDisplay?.runLabel || "").trim();
  if (explicit) return explicit;
  const snapshots = Array.isArray(run.kapitelSnapshots) ? run.kapitelSnapshots : [];
  if (snapshots.length === 1) {
    const snapshot = snapshots[0];
    const label = `${snapshot?.nummer ? `${snapshot.nummer} ` : ""}${snapshot?.title || ""}`.trim();
    if (label) return label;
  }
  const chapterCount = Array.isArray(run.kapitelIds) ? run.kapitelIds.length : 0;
  const pdfCount = Array.isArray(run.pdfIds) ? run.pdfIds.length : 0;
  if (chapterCount > 0 || pdfCount > 0) {
    return `${formatIntDe(chapterCount)} Kapitel • ${formatIntDe(pdfCount)} PDFs`;
  }
  return "PDF-Scan";
}

function buildKapitelNumber(snapshot: { nummer?: string | null } | Kapitel | null | undefined): string {
  return String(snapshot?.nummer || "").trim();
}

function buildKapitelTitle(
  snapshot:
    | ({
        title?: string | null;
        ueberschrift?: string | null;
      } & { nummer?: string | null })
    | Kapitel
    | null
    | undefined
): string {
  if (!snapshot) return "";
  const record = snapshot as { title?: string | null; ueberschrift?: string | null };
  return String(record.title || record.ueberschrift || "").trim();
}

function buildKapitelLabel(
  snapshot:
    | ({
        title?: string | null;
        ueberschrift?: string | null;
      } & { nummer?: string | null })
    | Kapitel
    | null
    | undefined
): string {
  const nummer = buildKapitelNumber(snapshot);
  const title = buildKapitelTitle(snapshot);
  return `${nummer ? `${nummer} ` : ""}${title || "Kapitel"}`.trim();
}

function buildChapterDocKey(chapterId: string, docId: string): string {
  return `${chapterId}::${docId}`;
}

let pdfjsUploadPromise: Promise<PdfJsModule> | null = null;

async function loadPdfJsForUpload(): Promise<PdfJsModule> {
  if (!pdfjsUploadPromise) pdfjsUploadPromise = import("pdfjs-dist") as Promise<PdfJsModule>;
  return pdfjsUploadPromise;
}

type FastApiErrorPayload = {
  detail?: unknown;
  error?: unknown;
  message?: unknown;
};

function getFastApiErrorDetailObject(payload: FastApiErrorPayload): Record<string, unknown> | null {
  return typeof payload.detail === "object" && payload.detail !== null && !Array.isArray(payload.detail)
    ? (payload.detail as Record<string, unknown>)
    : null;
}

function extractFastApiError(payload: FastApiErrorPayload): string {
  for (const candidate of [payload.detail, payload.error, payload.message]) {
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    if (typeof candidate === "object" && candidate !== null && !Array.isArray(candidate)) {
      for (const key of ["message", "detail", "error"]) {
        const value = (candidate as Record<string, unknown>)[key];
        if (typeof value === "string" && value.trim()) return value.trim();
      }
    }
  }
  return "Request failed.";
}

async function readFastApiError(res: Response): Promise<string> {
  try {
    const payload = (await res.json().catch(() => ({}))) as FastApiErrorPayload;
    return extractFastApiError(payload);
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

function isPdfScanRunActive(run: { status?: unknown } | null | undefined): boolean {
  const status = String(run?.status || "").trim();
  return status === "queued" || status === "running";
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
            ? "Wähle links die PDFs aus und starte den Scan. Du kannst mehrere Kapitel gleichzeitig auswählen; die Ergebnisse werden pro Kapitel und aggregiert gespeichert."
            : "Wähle links ein oder mehrere Kapitel, lade PDFs hoch und starte dann den Scan."}
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

function PdfScanAccessGate({
  previewMode,
  children,
}: {
  previewMode: boolean;
  children: React.ReactNode;
}) {
  const { user, canUsePdfScan, loading } = useAuth();

  if (!previewMode && !loading && user && !canUsePdfScan) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f5f7fb] px-6">
        <div className="max-w-[560px] rounded-[18px] border border-slate-200 bg-white px-8 py-10 text-center shadow-[0_18px_60px_rgba(15,23,42,0.08)]">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-rose-50 text-rose-600">
            <Ban className="h-5 w-5" />
          </div>
          <div className="mt-5 text-[24px] font-semibold tracking-[-0.02em] text-slate-950">Kein Zugriff auf PDF-Scan</div>
          <p className="mt-3 text-sm leading-7 text-slate-500">
            Dein Account ist angemeldet, aber PDF-Scan ist für diesen Nutzer noch nicht freigeschaltet.
          </p>
          <div className="mt-6">
            <Button asChild className="bg-[#1680cd] shadow-none hover:bg-[#0f76c2]">
              <Link href="/dashboard">Zurück zum Dashboard</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
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
  const [selectedKapitelIds, setSelectedKapitelIds] = useState<string[]>(() => {
    const initial = Array.isArray(preview?.initialSelectedKapitelIds) ? preview.initialSelectedKapitelIds : [];
    if (initial.length > 0) return initial.filter((value) => String(value || "").trim());
    const fallback = String(preview?.initialSelectedKapitelId || "").trim();
    return fallback ? [fallback] : [];
  });
  const [kapitelPickerOpen, setKapitelPickerOpen] = useState(false);
  const [kapitelFilter, setKapitelFilter] = useState("");

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

  const [chapterRows, setChapterRows] = useState<ChapterRow[]>(() => preview?.chapterRows ?? []);
  const [, setChapterRowsLoaded] = useState(() => previewMode);
  const [chapterDocRowsByChapterId, setChapterDocRowsByChapterId] = useState<Record<string, PdfDocRow[]>>(() => {
    const initialChapterId = String(preview?.initialActiveChapterId || preview?.initialSelectedKapitelId || "").trim();
    if (!initialChapterId || !(preview?.docRows?.length)) return {};
    return { [initialChapterId]: preview.docRows };
  });
  const [chapterDocRowsLoadedByChapterId, setChapterDocRowsLoadedByChapterId] = useState<Record<string, boolean>>(() => {
    const initialChapterId = String(preview?.initialActiveChapterId || preview?.initialSelectedKapitelId || "").trim();
    if (!initialChapterId || !previewMode) return {};
    return { [initialChapterId]: true };
  });
  const [openDocIds, setOpenDocIds] = useState<string[]>(() => {
    const initialChapterId = String(preview?.initialActiveChapterId || preview?.initialSelectedKapitelId || "").trim();
    if (!initialChapterId) return [];
    return (preview?.docRows ?? []).map((row) => buildChapterDocKey(initialChapterId, row.id));
  });
  const [startConfirmOpen, setStartConfirmOpen] = useState(false);
  const [duplicateKapitelConfirmOpen, setDuplicateKapitelConfirmOpen] = useState(false);
  const [duplicateKapitelConflictRunId, setDuplicateKapitelConflictRunId] = useState<string | null>(null);
  const [deleteConfirmPdf, setDeleteConfirmPdf] = useState<PdfRow | null>(null);

  const [chapterSectionRowsByChapterId, setChapterSectionRowsByChapterId] = useState<Record<string, Record<string, PdfSectionRow[]>>>(() => {
    const initialChapterId = String(preview?.initialActiveChapterId || preview?.initialSelectedKapitelId || "").trim();
    if (!initialChapterId || !preview?.sectionsByDocId) return {};
    return { [initialChapterId]: preview.sectionsByDocId };
  });
  const [chapterSectionRowsLoadedByChapterId, setChapterSectionRowsLoadedByChapterId] = useState<Record<string, boolean>>(() => {
    const initialChapterId = String(preview?.initialActiveChapterId || preview?.initialSelectedKapitelId || "").trim();
    if (!initialChapterId || !previewMode) return {};
    return { [initialChapterId]: true };
  });

  const [extractOpen, setExtractOpen] = useState(false);
  const [extractRequest, setExtractRequest] = useState<PdfExtractRequest | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [projectQuellen, setProjectQuellen] = useState<QuelleRow[]>([]);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const libraryDragDepthRef = useRef(0);
  const pdfColorRequestSeqRef = useRef<Map<string, number>>(new Map());
  const lastRunStatus = useRef<{ runId: string; status: string } | null>(null);
  const previousActiveRunIdRef = useRef<string | null>(null);
  const knownDocIdsForRunRef = useRef<Set<string>>(
    new Set(
      (preview?.docRows ?? []).map((row) =>
        buildChapterDocKey(String(preview?.initialActiveChapterId || preview?.initialSelectedKapitelId || "").trim(), row.id)
      )
    )
  );
  const activeRunCookieKey = useMemo(() => `pdf_scan_active_run_${projektId}`, [projektId]);

  const kapitelById = useMemo(() => {
    const map = new Map<string, Kapitel>();
    for (const kapitel of kapitels) map.set(kapitel.id, kapitel);
    return map;
  }, [kapitels]);

  const selectedKapitelIdSet = useMemo(() => new Set(selectedKapitelIds), [selectedKapitelIds]);

  const selectedKapitelRows = useMemo(
    () => kapitels.filter((item) => selectedKapitelIdSet.has(item.id)),
    [kapitels, selectedKapitelIdSet]
  );
  const selectedKapitelPreviewRows = useMemo(() => selectedKapitelRows.slice(0, 3), [selectedKapitelRows]);
  const hiddenSelectedKapitelCount = Math.max(0, selectedKapitelRows.length - selectedKapitelPreviewRows.length);
  const filteredKapitelRows = useMemo(() => {
    const q = kapitelFilter.trim().toLowerCase();
    if (!q) return kapitels;
    return kapitels.filter((kapitel) => {
      const nummer = String(kapitel.nummer || "").toLowerCase();
      const title = String(kapitel.title || "").toLowerCase();
      return nummer.includes(q) || title.includes(q);
    });
  }, [kapitelFilter, kapitels]);

  const primarySelectedKapitel = selectedKapitelRows[0] ?? null;

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

  const selectedKapitelRunningRuns = useMemo(() => {
    if (selectedKapitelIdSet.size === 0) return [];
    return pdfScanRuns.filter(
      (run) =>
        isPdfScanRunActive(run) &&
        Array.isArray(run.kapitelIds) &&
        run.kapitelIds.some((kapitelId) => selectedKapitelIdSet.has(String(kapitelId || "").trim()))
    );
  }, [pdfScanRuns, selectedKapitelIdSet]);

  const sameKapitelRunningRun = selectedKapitelRunningRuns[0] ?? null;

  const activeRun = useMemo(() => {
    if (activeRunId) {
      const found = pdfScanRuns.find((run) => run.id === activeRunId);
      if (found) return found;
    }
    if (selectedKapitelIds.length > 0) {
      return (
        pdfScanRuns.find(
          (run) =>
            Array.isArray(run.kapitelIds) &&
            selectedKapitelIds.every((kapitelId) => run.kapitelIds.includes(kapitelId))
        ) ?? null
      );
    }
    return pdfScanRuns[0] ?? null;
  }, [activeRunId, pdfScanRuns, selectedKapitelIds]);

  const activeRunChapterRows = useMemo(() => {
    const runChapterIds = Array.isArray(activeRun?.kapitelIds)
      ? activeRun.kapitelIds.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    const chapterMap = new Map(chapterRows.map((row) => [row.chapterId, row]));
    return runChapterIds.map((chapterId, index) => {
      const existing = chapterMap.get(chapterId);
      if (existing) return existing;
      const kapitel = kapitelById.get(chapterId);
      return {
        id: chapterId,
        chapterId,
        chapterOrder: index,
        kapitelSnapshot: {
          id: chapterId,
          nummer: kapitel?.nummer,
          title: kapitel?.title,
          ueberschrift: kapitel?.title,
          thema: kapitel?.thema,
        },
        status: "queued",
        usefulPdfCount: 0,
        documentCount: 0,
        visibleSectionCount: 0,
        topSectionCount: 0,
        createdAt: Timestamp.now(),
        updatedAt: Timestamp.now(),
        } as ChapterRow;
    });
  }, [activeRun?.kapitelIds, chapterRows, kapitelById]);
  const activeRunChapterIds = useMemo(
    () => activeRunChapterRows.map((row) => String(row.chapterId || "").trim()).filter(Boolean),
    [activeRunChapterRows]
  );

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

  const pdfDeleteBlockers = useMemo(() => {
    const blockers = new Map<string, { runId: string; isActive: boolean }>();

    for (const run of pdfScanRuns) {
      const status = String(run.status || "").trim();
      if (status !== "queued" && status !== "running" && status !== "success") continue;

      const isActive = isPdfScanRunActive(run);
      for (const rawPdfId of Array.isArray(run.pdfIds) ? run.pdfIds : []) {
        const pdfId = String(rawPdfId || "").trim();
        if (!pdfId) continue;

        const existing = blockers.get(pdfId);
        if (!existing || (isActive && !existing.isActive)) {
          blockers.set(pdfId, { runId: run.id, isActive });
        }
      }
    }

    return blockers;
  }, [pdfScanRuns]);

  useEffect(() => {
    if (!previewMode && !activeRunCookieRestored) return;
    if (selectedKapitelIds.length > 0) return;
    if (activeRun?.kapitelIds?.length) {
      const nextKapitelIds = activeRun.kapitelIds.filter((value): value is string => Boolean(String(value || "").trim()));
      setSelectedKapitelIds(nextKapitelIds);
      return;
    }
    if (kapitels.length) {
      const firstKapitelId = kapitels[0]?.id ?? null;
      setSelectedKapitelIds(firstKapitelId ? [firstKapitelId] : []);
    }
  }, [activeRun?.kapitelIds, activeRunCookieRestored, kapitels, previewMode, selectedKapitelIds]);

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
    setChapterRows([]);
    setChapterRowsLoaded(previewMode);
    setChapterDocRowsByChapterId({});
    setChapterDocRowsLoadedByChapterId({});
    setChapterSectionRowsByChapterId({});
    setChapterSectionRowsLoadedByChapterId({});
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
    const nextKapitelIds = Array.isArray(cookieRun.kapitelIds)
      ? cookieRun.kapitelIds.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    if (nextKapitelIds.length > 0) {
      setSelectedKapitelIds(nextKapitelIds);
    }
    setActiveRunCookieRestored(true);
  }, [activeRunCookieKey, activeRunCookieRestored, activeRunId, pdfScanRuns, previewMode, runsLoaded]);

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
      setChapterRows([]);
      setChapterRowsLoaded(false);
      return;
    }
    setChapterRowsLoaded(false);
    const q = query(quellenFinderPdfScanChaptersCol(firestoreClient, user.uid, projektId, activeRun.id), limit(100));
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs
          .map((entry) => ({ id: entry.id, ...(entry.data() as PdfScanChapterDoc) }))
          .sort((a, b) => Number(a.chapterOrder || 0) - Number(b.chapterOrder || 0));
        setChapterRows(next);
        setChapterRowsLoaded(true);
      },
      (err) => {
        console.error("Failed to load pdfScanChapters:", err);
        setChapterRows([]);
        setChapterRowsLoaded(true);
      }
    );
  }, [activeRun?.id, previewMode, projektId, user?.uid]);

  useEffect(() => {
    if (!previewMode) return;
    setChapterRows(preview?.chapterRows ?? []);
    setChapterRowsLoaded(true);
    const initialChapterId = String(preview?.initialActiveChapterId || preview?.initialSelectedKapitelId || "").trim();
    setChapterDocRowsByChapterId(initialChapterId && preview?.docRows ? { [initialChapterId]: preview.docRows } : {});
    setChapterDocRowsLoadedByChapterId(initialChapterId ? { [initialChapterId]: true } : {});
    setChapterSectionRowsByChapterId(initialChapterId && preview?.sectionsByDocId ? { [initialChapterId]: preview.sectionsByDocId } : {});
    setChapterSectionRowsLoadedByChapterId(initialChapterId ? { [initialChapterId]: true } : {});
  }, [previewMode, preview]);
 
  useEffect(() => {
    if (previewMode) return;
    if (!user?.uid || !projektId || !activeRun?.id || activeRunChapterIds.length === 0) {
      setChapterDocRowsByChapterId({});
      setChapterDocRowsLoadedByChapterId({});
      setChapterSectionRowsByChapterId({});
      setChapterSectionRowsLoadedByChapterId({});
      return;
    }

    setChapterDocRowsLoadedByChapterId({});
    setChapterSectionRowsLoadedByChapterId({});

    const unsubscribes: Array<() => void> = [];

    for (const chapterId of activeRunChapterIds) {
      const docsQuery = query(quellenFinderPdfScanChapterDocsCol(firestoreClient, user.uid, projektId, activeRun.id, chapterId), limit(200));
      unsubscribes.push(
        onSnapshot(
          docsQuery,
          (snap) => {
            const next = snap.docs
              .map((entry) => ({ id: entry.id, ...(entry.data() as PdfScanChapterDocSummaryDoc) }))
              .sort((a, b) => {
                const scoreDiff = readTopScore(b) - readTopScore(a);
                if (scoreDiff !== 0) return scoreDiff;
                const countDiff = Number(b.visibleSectionCount || 0) - Number(a.visibleSectionCount || 0);
                if (countDiff !== 0) return countDiff;
                return String(a.docTitle || a.pdfLabel || "").localeCompare(String(b.docTitle || b.pdfLabel || ""), "de");
              });
            setChapterDocRowsByChapterId((prev) => ({ ...prev, [chapterId]: next }));
            setChapterDocRowsLoadedByChapterId((prev) => ({ ...prev, [chapterId]: true }));
          },
          (err) => {
            console.error(`Failed to load pdfScanChapter docs for ${chapterId}:`, err);
            setChapterDocRowsByChapterId((prev) => ({ ...prev, [chapterId]: [] }));
            setChapterDocRowsLoadedByChapterId((prev) => ({ ...prev, [chapterId]: true }));
          }
        )
      );

      const sectionsQuery = query(
        quellenFinderPdfScanChapterSectionsCol(firestoreClient, user.uid, projektId, activeRun.id, chapterId),
        limit(5000)
      );
      unsubscribes.push(
        onSnapshot(
          sectionsQuery,
          (snap) => {
            const rows = snap.docs
              .map((entry) => ({ id: entry.id, ...(entry.data() as PdfScanChapterSectionDoc) }))
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
            setChapterSectionRowsByChapterId((prev) => ({ ...prev, [chapterId]: grouped }));
            setChapterSectionRowsLoadedByChapterId((prev) => ({ ...prev, [chapterId]: true }));
          },
          (err) => {
            console.error(`Failed to load pdfScanChapter sections for ${chapterId}:`, err);
            setChapterSectionRowsByChapterId((prev) => ({ ...prev, [chapterId]: {} }));
            setChapterSectionRowsLoadedByChapterId((prev) => ({ ...prev, [chapterId]: true }));
          }
        )
      );
    }

    return () => {
      unsubscribes.forEach((unsubscribe) => unsubscribe());
    };
  }, [activeRun?.id, activeRunChapterIds, previewMode, projektId, user?.uid]);

  useEffect(() => {
    const nextDocKeys = activeRunChapterIds.flatMap((chapterId) =>
      (chapterDocRowsByChapterId[chapterId] ?? []).map((row) => buildChapterDocKey(chapterId, row.id))
    );
    const docKeySet = new Set(nextDocKeys);
    setOpenDocIds((prev) => {
      const kept = prev.filter((docKey) => docKeySet.has(docKey));
      if (kept.length > 0) return kept;
      return nextDocKeys.length > 0 ? [nextDocKeys[0]!] : [];
    });
    knownDocIdsForRunRef.current = new Set(nextDocKeys);
  }, [activeRunChapterIds, chapterDocRowsByChapterId]);

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
        const totalVisibleSectionCount =
          typeof activeRun.pdfScanSummary?.totalVisibleSectionCount === "number"
            ? activeRun.pdfScanSummary.totalVisibleSectionCount
            : typeof activeRun.pdfScanSectionCount === "number"
              ? activeRun.pdfScanSectionCount
              : null;
        toast.success("PDF-Scan abgeschlossen", {
          description:
            typeof totalVisibleSectionCount === "number"
              ? `${formatIntDe(totalVisibleSectionCount)} sichtbare Sections`
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
  }, [activeRun?.errorMessage, activeRun?.id, activeRun?.pdfScanSectionCount, activeRun?.pdfScanSummary?.totalVisibleSectionCount, activeRun?.status]);

  const toggleSelectedKapitel = (kapitelId: string, nextChecked: boolean) => {
    const normalizedKapitelId = String(kapitelId || "").trim();
    if (!normalizedKapitelId) return;
    setSelectedKapitelIds((prev) => {
      const next = new Set(prev);
      if (nextChecked) next.add(normalizedKapitelId);
      else next.delete(normalizedKapitelId);
      return Array.from(next);
    });
  };

  const selectRun = (run: RunRow) => {
    setActiveRunId(run.id);
    const runKapitelIds = Array.isArray(run.kapitelIds)
      ? run.kapitelIds.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    if (runKapitelIds.length > 0) {
      setSelectedKapitelIds(runKapitelIds);
    }
  };

  const showPdfSelectionLimitToast = () => {
    toast.error(`Maximal ${PDF_SCAN_MAX_PDFS_PER_RUN} PDFs pro Scan`, {
      description: "Reduziere die Auswahl oder starte mehrere Läufe.",
    });
  };

  const togglePdfSelection = (pdfId: string, nextChecked: boolean) => {
    let blockedByLimit = false;
    setSelectedPdfIds((prev) => {
      const next = new Set(prev);
      if (nextChecked) {
        if (!next.has(pdfId) && next.size >= PDF_SCAN_MAX_PDFS_PER_RUN) {
          blockedByLimit = true;
          return prev;
        }
        next.add(pdfId);
      } else {
        next.delete(pdfId);
      }
      return Array.from(next);
    });
    if (blockedByLimit) showPdfSelectionLimitToast();
  };

  const setVisibleSelection = (checked: boolean) => {
    let blockedByLimit = false;
    setSelectedPdfIds((prev) => {
      const next = new Set(prev);
      for (const pdf of filteredPdfs) {
        if (checked) {
          if (next.has(pdf.id)) continue;
          if (next.size >= PDF_SCAN_MAX_PDFS_PER_RUN) {
            blockedByLimit = true;
            continue;
          }
          next.add(pdf.id);
        } else {
          next.delete(pdf.id);
        }
      }
      return Array.from(next);
    });
    if (blockedByLimit) showPdfSelectionLimitToast();
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
    }
    const oversized = fileList.filter((file) => file.size > PDF_UPLOAD_MAX_BYTES);
    if (oversized.length) {
      toast.error("PDF zu groß", {
        description: `${oversized
          .map((file) => file.name)
          .slice(0, 3)
          .join(", ")} überschreitet das 100-MB-Limit.`,
      });
    }
    const emptyFiles = fileList.filter((file) => file.size <= 0);
    if (emptyFiles.length) {
      toast.error("Leere PDF-Datei", {
        description: emptyFiles
          .map((file) => file.name)
          .slice(0, 3)
          .join(", "),
      });
    }

    const acceptedFiles = fileList.filter(
      (file) =>
        String(file.name || "").toLowerCase().endsWith(".pdf") &&
        file.size > 0 &&
        file.size <= PDF_UPLOAD_MAX_BYTES
    );
    if (acceptedFiles.length === 0) {
      return;
    }

    setUploading(true);
    setUploadProgress({ done: 0, total: acceptedFiles.length });

    try {
      const knownPdfs = [...pdfs];
      const skippedDuplicates: string[] = [];
      let uploadedCount = 0;

      for (let index = 0; index < acceptedFiles.length; index += 1) {
        const file = acceptedFiles[index]!;
        const originalName = String(file.name || "document.pdf").trim() || "document.pdf";
        setUploadProgress({ done: index, total: acceptedFiles.length });
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
          setUploadProgress({ done: index + 1, total: acceptedFiles.length });
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
          setUploadProgress({ done: index + 1, total: acceptedFiles.length });
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
          setUploadProgress({ done: index + 1, total: acceptedFiles.length });
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
        setUploadProgress({ done: index + 1, total: acceptedFiles.length });
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

    const blocker = pdfDeleteBlockers.get(pdf.id);
    if (blocker) {
      toast.error("PDF kann nicht gelöscht werden", {
        description: blocker.isActive
          ? `Die PDF wird im aktiven Scan ${blocker.runId} verwendet.`
          : `Die PDF wird von Run ${blocker.runId} referenziert.`,
      });
      return;
    }

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

    const blocker = pdfDeleteBlockers.get(pdf.id);
    if (blocker) {
      toast.error("PDF kann nicht gelöscht werden", {
        description: blocker.isActive
          ? `Die PDF wird im aktiven Scan ${blocker.runId} verwendet.`
          : `Die PDF wird von Run ${blocker.runId} referenziert.`,
      });
      return;
    }

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
    if (selectedKapitelIds.length === 0) {
      toast.error("Bitte zuerst mindestens ein Kapitel auswählen.");
      return;
    }
    if (selectedPdfIds.length === 0) {
      toast.error("Bitte mindestens ein PDF auswählen.");
      return;
    }
    if (selectedPdfIds.length > PDF_SCAN_MAX_PDFS_PER_RUN) {
      showPdfSelectionLimitToast();
      return;
    }
    setDuplicateKapitelConfirmOpen(false);
    setDuplicateKapitelConflictRunId(null);
    setStartConfirmOpen(true);
  };

  const handleStartButtonClick = () => {
    if (selectedPdfIds.length === 0 && !previewMode && !uploading) {
      setLibraryExpanded(true);
      setLibraryManagerOpen(true);
      return;
    }
    startPdfScan();
  };

  const confirmStartPdfScan = async (allowDuplicateKapitelRun = false) => {
    if (selectedKapitelIds.length === 0 || selectedPdfIds.length === 0) return;
    if (selectedPdfIds.length > PDF_SCAN_MAX_PDFS_PER_RUN) {
      showPdfSelectionLimitToast();
      return;
    }

    if (sameKapitelRunningRun && !allowDuplicateKapitelRun) {
      setStartConfirmOpen(false);
      setDuplicateKapitelConflictRunId(sameKapitelRunningRun.id);
      setDuplicateKapitelConfirmOpen(true);
      return;
    }

    setStartConfirmOpen(false);
    setDuplicateKapitelConfirmOpen(false);
    setDuplicateKapitelConflictRunId(null);
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
        kapitel_ids: selectedKapitelIds,
        confirm_duplicate_kapitel_run: allowDuplicateKapitelRun,
        pdf_ids: selectedPdfIds,
      }),
    });

    if (!res.ok) {
      const payload = (await res.json().catch(() => ({}))) as FastApiErrorPayload;
      const detail = extractFastApiError(payload);
      const detailObject = getFastApiErrorDetailObject(payload);
      if (res.status === 402) {
        toast.error("Nicht genügend Credits", { description: detail });
        return;
      }
      if (res.status === 409) {
        const code = typeof detailObject?.code === "string" ? detailObject.code : "";
        const runId = typeof detailObject?.run_id === "string" ? detailObject.run_id : null;
        if ((code === "overlapping_kapitel_scan_running" || code === "same_kapitel_scan_running") && !allowDuplicateKapitelRun) {
          setDuplicateKapitelConflictRunId(runId);
          setDuplicateKapitelConfirmOpen(true);
          return;
        }
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
  const chapterResultGroups = useMemo(
    () =>
      activeRunChapterRows.map((row) => {
        const chapterId = String(row.chapterId || "").trim();
        const docRows = chapterDocRowsByChapterId[chapterId] ?? [];
        const sectionRowsByDocId = chapterSectionRowsByChapterId[chapterId] ?? {};
        const loadedDocs = Boolean(chapterDocRowsLoadedByChapterId[chapterId]);
        const loadedSections = Boolean(chapterSectionRowsLoadedByChapterId[chapterId]);
        const sectionCount =
          typeof row.visibleSectionCount === "number"
            ? row.visibleSectionCount
            : docRows.reduce((sum, docRow) => sum + ((sectionRowsByDocId[docRow.id] ?? []).length || 0), 0);
        return {
          chapterId,
          chapterRow: row,
          heading: buildKapitelLabel(row.kapitelSnapshot),
          numberLabel: buildKapitelNumber(row.kapitelSnapshot),
          docRows,
          sectionRowsByDocId,
          loadedDocs,
          loadedSections,
          visibleSectionCount: sectionCount,
          usefulPdfCount: typeof row.usefulPdfCount === "number" ? row.usefulPdfCount : docRows.filter((docRow) => docRow.hasUsefulInformation).length,
        };
      }),
    [
      activeRunChapterRows,
      chapterDocRowsByChapterId,
      chapterDocRowsLoadedByChapterId,
      chapterSectionRowsByChapterId,
      chapterSectionRowsLoadedByChapterId,
    ]
  );
  const chapterCount =
    typeof activeRun?.pdfScanSummary?.chapterCount === "number" ? activeRun.pdfScanSummary.chapterCount : activeRunChapterRows.length;
  const visibleSectionCount =
    typeof activeRun?.pdfScanSummary?.totalVisibleSectionCount === "number"
      ? activeRun.pdfScanSummary.totalVisibleSectionCount
      : chapterResultGroups.reduce((sum, group) => sum + group.visibleSectionCount, 0);
  const usefulPdfCount =
    typeof activeRun?.pdfScanSummary?.usefulPdfCountAnyChapter === "number"
      ? activeRun.pdfScanSummary.usefulPdfCountAnyChapter
      : new Set(
          chapterResultGroups.flatMap((group) =>
            group.docRows.filter((row) => row.hasUsefulInformation).map((row) => String(row.docId || row.id || "").trim()).filter(Boolean)
          )
        ).size;
  const runChapterNumberPills = activeRunChapterRows
    .map((row) => buildKapitelNumber(row.kapitelSnapshot))
    .filter((value, index, values) => Boolean(value) && values.indexOf(value) === index);
  const chapterGroupsWithResults = chapterResultGroups.filter((group) => group.docRows.length > 0);
  const allChapterResultsLoaded =
    chapterResultGroups.length > 0 &&
    chapterResultGroups.every((group) => group.loadedDocs && group.loadedSections);
  const activeRunTitle = activeRun
    ? buildKapitelLabel(activeRunChapterRows[0]?.kapitelSnapshot ?? primarySelectedKapitel)
    : "PDF-Scan";
  const runCostUsd = readRunCostUsd(activeRun);
  const selectedPdfPreviewRows = selectedPdfRows.slice(0, 3);
  const hiddenSelectedPdfCount = Math.max(0, selectedPdfRows.length - selectedPdfPreviewRows.length);
  const startButtonLabel =
    selectedKapitelIds.length > 0 || selectedPdfIds.length > 0
      ? `Scan starten (${formatIntDe(selectedKapitelIds.length)} Kap. / ${formatIntDe(selectedPdfIds.length)} PDFs)`
      : "Scan starten";
  const currentStepNumber = isDone
    ? PDF_SCAN_PIPELINE_STEPS.length
    : activeStepIndex >= 0
      ? activeStepIndex + 1
      : 0;
  const currentStepLabel =
    PDF_SCAN_PIPELINE_STEPS[isDone ? PDF_SCAN_PIPELINE_STEPS.length - 1 : Math.max(0, activeStepIndex)]?.label ?? "Pipeline";
  const runOutcomeLabel = isDone ? "Erfolgreich" : isCancelled ? "Abgebrochen" : isError ? "Fehler" : "Läuft";
  const duplicateKapitelPromptRunId = duplicateKapitelConflictRunId ?? sameKapitelRunningRun?.id ?? null;

  const startDisabledReasons: string[] = [];
  if (previewMode) startDisabledReasons.push("Der Scan ist in dieser Vorschau deaktiviert.");
  if (selectedKapitelIds.length === 0) startDisabledReasons.push("Wähle zuerst mindestens ein Kapitel aus.");
  if (selectedPdfIds.length === 0) startDisabledReasons.push("Wähle mindestens eine PDF aus der Bibliothek aus.");
  if (selectedPdfIds.length > PDF_SCAN_MAX_PDFS_PER_RUN) {
    startDisabledReasons.push(`Maximal ${PDF_SCAN_MAX_PDFS_PER_RUN} PDFs pro Scan sind erlaubt.`);
  }
  if (uploading) startDisabledReasons.push("Warte, bis der aktuelle PDF-Upload abgeschlossen ist.");
  const canStart = startDisabledReasons.length === 0;
  const canOpenLibraryFromStart = !previewMode && !uploading && selectedPdfIds.length === 0;
  const startButtonEnabled = canStart || canOpenLibraryFromStart;

  return (
    <PdfScanAccessGate previewMode={previewMode}>
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
        <aside className="flex min-h-0 w-[320px] shrink-0 flex-col overflow-hidden border-r border-slate-200 bg-white">
          <div className="shrink-0 space-y-4 border-b border-slate-200 px-5 py-5">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-medium text-slate-600">Kapitel auswählen</div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-9 rounded-[6px] border-slate-200 bg-white px-4 text-sm shadow-none"
                  onClick={() => setKapitelPickerOpen(true)}
                >
                  Auswählen{selectedKapitelIds.length > 0 ? ` (${formatIntDe(selectedKapitelIds.length)})` : ""}
                </Button>
              </div>

              <div className="space-y-1.5">
                {selectedKapitelPreviewRows.length > 0 ? (
                  selectedKapitelPreviewRows.map((kapitel) => (
                    <div
                      key={kapitel.id}
                      className="flex items-start gap-2.5 rounded-[8px] bg-slate-50 px-3 py-2"
                    >
                      <div className="shrink-0 pt-0.5 text-[13px] font-semibold tabular-nums text-sky-700">
                        {kapitel.nummer || "–"}
                      </div>
                      <div className="min-w-0 flex-1 text-[14px] leading-5 text-slate-800 line-clamp-2">
                        {kapitel.title}
                      </div>
                      <button
                        type="button"
                        className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center text-slate-400 transition-colors hover:text-slate-700"
                        onClick={() => toggleSelectedKapitel(kapitel.id, false)}
                        title="Aus Auswahl entfernen"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))
                ) : (
                  <div className="rounded-[8px] border border-dashed border-slate-200 px-3 py-3 text-sm text-slate-500">
                    Noch kein Kapitel ausgewählt.
                  </div>
                )}
                {hiddenSelectedKapitelCount > 0 ? (
                  <button
                    type="button"
                    className="text-sm text-sky-700 transition-colors hover:text-sky-800"
                    onClick={() => setKapitelPickerOpen(true)}
                  >
                    +{formatIntDe(hiddenSelectedKapitelCount)} weitere...
                  </button>
                ) : null}
              </div>
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
                <div className="mt-3 rounded-[14px] border border-slate-200 bg-white p-3.5 shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-baseline gap-1.5">
                        <div className="text-[18px] font-semibold leading-none tracking-[-0.03em] text-slate-950">{formatIntDe(pdfs.length)}</div>
                        <div className="truncate text-[14px] font-medium leading-5 text-slate-900">PDFs verfügbar</div>
                      </div>
                      <div className="mt-1 text-[14px] leading-6 text-slate-500 whitespace-nowrap">{formatIntDe(selectedPdfIds.length)} für Scan ausgewählt</div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-9 shrink-0 rounded-[4px] border-slate-200 bg-white px-3 text-[13px] shadow-none"
                      onClick={() => setLibraryManagerOpen(true)}
                    >
                      Verwalten
                    </Button>
                  </div>

                  <div className="mt-4 border-t border-slate-200 pt-4">
                    <div className="text-[13px] font-medium text-slate-500">Ausgewählte PDFs:</div>
                    {selectedPdfPreviewRows.length === 0 ? (
                      <div className="mt-3 text-sm leading-6 text-slate-500">Noch keine PDFs ausgewählt.</div>
                    ) : (
                      <TooltipProvider delayDuration={120}>
                        <div className="mt-3 space-y-2">
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
                  {startButtonLabel}
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
                          {startButtonLabel}
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
                  const runChapterCount =
                    Array.isArray(run.kapitelIds) && run.kapitelIds.length > 0
                      ? run.kapitelIds.length
                      : typeof run.pdfScanSummary?.chapterCount === "number"
                        ? run.pdfScanSummary.chapterCount
                        : 0;
                  const primaryRunSnapshot =
                    Array.isArray(run.kapitelSnapshots) && run.kapitelSnapshots.length > 0 ? run.kapitelSnapshots[0] : null;
                  const label =
                    runChapterCount > 1
                      ? `${formatIntDe(runChapterCount)} Kapitel`
                      : primaryRunSnapshot
                        ? buildKapitelLabel(primaryRunSnapshot)
                        : buildPdfScanRunLabel(run);
                  const subtitle =
                    run.status === "queued" || run.status === "running"
                      ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  Läuft...`
                      : run.status === "success"
                        ? `${formatTimeHm(run.startedAt ?? run.createdAt)}  ${formatIntDe(run.pdfScanSummary?.documentCount ?? run.pdfScanCounts?.aggregateDocCount ?? 0)} PDFs · ${formatIntDe(run.pdfScanSummary?.usefulPdfCountAnyChapter ?? 0)} nützlich`
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
                        <div className="text-[18px] font-semibold tracking-[-0.02em] text-slate-950">{activeRunTitle}</div>
                        <div className="mt-1 text-sm text-slate-500">
                          Gestartet: {formatDateTimeWithSeconds(runStartedAt)}
                          {runFinishedAt ? <> · Abgeschlossen: {formatDateTimeWithSeconds(runFinishedAt)}</> : null}
                        </div>
                        {runChapterNumberPills.length > 0 ? (
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {runChapterNumberPills.map((nummer) => (
                              <span
                                key={nummer}
                                className="inline-flex items-center rounded-[6px] bg-slate-100 px-2.5 py-0.5 text-[13px] font-medium text-slate-900"
                              >
                                {nummer}
                              </span>
                            ))}
                          </div>
                        ) : null}
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
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-8 rounded-[4px] border-slate-200 bg-white px-3 text-xs shadow-none"
                            onClick={cancelPdfScan}
                            disabled={isCancelRequested}
                          >
                            {isCancelRequested ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <X className="mr-2 h-3.5 w-3.5" />}
                            {isCancelRequested ? "Wird abgebrochen..." : "Abbrechen"}
                          </Button>
                        ) : null}
                      </div>
                    </div>

                    <Card className="rounded-[14px] border border-slate-200 bg-white shadow-sm">
                      <div className="px-4 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-2.5">
                          <div className="min-w-0">
                            <div className="text-[14px] font-semibold tracking-[-0.01em] text-slate-950">Pipeline-Status</div>
                          </div>
                          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            <span className="tabular-nums">
                              {formatIntDe(currentStepNumber)} / {formatIntDe(PDF_SCAN_PIPELINE_STEPS.length)} Schritte
                            </span>
                          </div>
                        </div>

                        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs">
                          <div className="flex items-center gap-2 text-slate-600">
                            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" /> : isDone ? <Check className="h-3.5 w-3.5 text-sky-600" /> : null}
                            <span>
                              {isDone ? "Erfolgreich abgeschlossen" : isCancelled ? "Abgebrochen" : isError ? "Fehlgeschlagen" : `${currentStepLabel}: ${stageLabel(activeRun)}`}
                            </span>
                          </div>
                          <div className="tabular-nums text-slate-500">
                            {formatIntDe(currentStepNumber)}/{formatIntDe(PDF_SCAN_PIPELINE_STEPS.length)} abgeschlossen
                          </div>
                        </div>

                        <div className="mt-2.5">
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
                        </div>

                        {isError ? (
                          <div className="mt-4 rounded-[12px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                            {String(activeRun.errorMessage || "").trim() || "Unbekannter Fehler"}
                          </div>
                        ) : null}
                      </div>
                    </Card>

                    {!running ? (
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        <Card className="rounded-[14px] border border-slate-200 bg-white px-4 py-3.5 shadow-sm">
                          <div className="text-[13px] text-slate-500">Status</div>
                          <div
                            className={cn(
                              "mt-4.5 text-[16px] font-semibold tracking-[-0.02em]",
                              isError ? "text-rose-600" : isCancelled ? "text-slate-500" : "text-sky-700"
                            )}
                          >
                            {runOutcomeLabel}
                          </div>
                        </Card>
                        <Card className="rounded-[14px] border border-slate-200 bg-white px-4 py-3.5 shadow-sm">
                          <div className="text-[13px] text-slate-500">Kapitel</div>
                          <div className="mt-4.5 text-[16px] font-semibold tracking-[-0.02em] text-slate-950">{formatIntDe(chapterCount)}</div>
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
                    ) : null}
                  </div>
                </>
              ) : null}

              {!activeRun ? (
                <MainEmptyState selectedKapitel={primarySelectedKapitel} />
              ) : (
                <div className="space-y-8 pb-6 pt-2">
                  {running && chapterGroupsWithResults.length === 0 ? null : !running && !allChapterResultsLoaded ? (
                    <ResultSkeleton />
                  ) : chapterGroupsWithResults.length === 0 ? (
                    <Card className="rounded-[14px] border border-dashed border-slate-200 bg-white px-5 py-14 text-center shadow-none">
                      <div className="text-base font-medium text-slate-900">
                        {running ? "Noch keine finalen Ergebnisse" : "Keine sichtbaren Sections"}
                      </div>
                      <div className="mt-2 text-sm leading-7 text-slate-500">
                        {running
                          ? "Die Ergebnisse erscheinen nach Phase G und dem Persistieren der finalen Section-Scores."
                          : "Für diesen Run wurden keine finalen Sections gespeichert."}
                      </div>
                    </Card>
                  ) : (
                    chapterGroupsWithResults.map((group) => {
                      const groupOpenValues = openDocIds.filter((value) => value.startsWith(`${group.chapterId}::`));
                      return (
                        <section key={group.chapterId} className="space-y-3">
                          <div className="min-w-0">
                            <div className="text-[18px] font-semibold tracking-[-0.02em] text-slate-950">{group.heading}</div>
                            <div className="mt-1 text-sm text-slate-500">
                              {formatIntDe(group.docRows.length)} PDFs · {formatIntDe(group.visibleSectionCount)} relevante Abschnitte
                            </div>
                          </div>

                          <div className="border-t border-slate-200 pt-3">
                          <div className="border-l-2 border-[#a9c4dd] pl-4">
                            <Accordion
                              type="multiple"
                              value={groupOpenValues}
                              onValueChange={(value) =>
                                setOpenDocIds((prev) => [...prev.filter((entry) => !entry.startsWith(`${group.chapterId}::`)), ...value])
                              }
                              className="space-y-3"
                            >
                              {group.docRows.map((pdfDoc) => {
                                const pdfMeta = pdfsById.get(String(pdfDoc.pdfId || ""));
                                const topScore = typeof pdfDoc.topSectionScore === "number" ? pdfDoc.topSectionScore : null;
                                const docKey = buildChapterDocKey(group.chapterId, pdfDoc.id);
                                const isOpen = openDocIds.includes(docKey);
                                const sectionRows = group.sectionRowsByDocId[pdfDoc.id] ?? [];
                                const topScoreClass =
                                  topScore !== null && topScore >= 60
                                    ? "bg-sky-50 text-sky-700"
                                    : topScore !== null && topScore >= 40
                                      ? "bg-amber-50 text-amber-700"
                                      : "bg-slate-100 text-slate-600";

                                return (
                                  <AccordionItem
                                    key={docKey}
                                    value={docKey}
                                    className="overflow-hidden rounded-[14px] border border-slate-200/90 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]"
                                  >
                                    <AccordionTrigger className="items-center px-6 py-8 hover:no-underline [&>svg]:hidden">
                                      <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_120px] items-center gap-5 text-left">
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
                                              {sectionRows.length > 0 ? ` · ${formatIntDe(sectionRows.length)} relevant` : ""}
                                            </div>
                                          </div>
                                        </div>

                                        <div className="flex h-full items-center justify-end gap-3 text-right">
                                          <div className={cn("inline-flex rounded-[6px] px-3 py-1 text-[13px] font-semibold tabular-nums", topScoreClass)}>
                                            Score: {topScore !== null ? formatScore(topScore, 0) : "—"}
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

                                    <AccordionContent className="border-t border-slate-200 bg-white pb-0">
                                      {!isOpen || !group.loadedSections ? (
                                        <div className="space-y-3 px-5 pb-6 pt-4">
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
                                        <div className="px-5 pb-6 pt-4">
                                          <div className="rounded-[14px] border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                                            Für dieses PDF wurden keine finalen Sections geladen.
                                          </div>
                                        </div>
                                      ) : (
                                        <div className="bg-white pb-5">
                                          <div className="space-y-2 px-5 py-4">
                                            {sectionRows.map((section) => {
                                              const sectionScore = typeof section.score0To100 === "number" ? section.score0To100 : null;
                                              const sectionScoreClass =
                                                sectionScore !== null && sectionScore >= 60
                                                  ? "bg-sky-700 text-white"
                                                  : sectionScore !== null && sectionScore >= 40
                                                    ? "bg-sky-50 text-sky-700"
                                                    : "bg-slate-100 text-slate-700";
                                              return (
                                                <div key={section.id} className="rounded-[12px] bg-slate-50 px-4 py-4">
                                                  <div className="flex items-center justify-between gap-4">
                                                    <div className="flex min-w-0 items-center gap-4">
                                                      <div className="shrink-0">
                                                        <div className={cn("inline-flex min-w-[48px] items-center justify-center rounded-[6px] px-2.5 py-1 text-[12px] font-semibold leading-none tabular-nums", sectionScoreClass)}>
                                                          {sectionScore !== null ? `${formatScore(sectionScore, 0)}%` : "—"}
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
                                                            <Badge key={`${section.id}_${subpointId}`} variant="outline" className="rounded-[4px] border-slate-200 bg-white px-1.5 py-0 text-[11px] text-slate-600">
                                                              {subpointId}
                                                            </Badge>
                                                          ))}
                                                        </div>
                                                      </div>
                                                    </div>

                                                    <div className="shrink-0">
                                                      <Button
                                                        variant="ghost"
                                                        className="h-8 rounded-[6px] px-3 text-[13px] text-slate-700 shadow-none hover:bg-white hover:text-slate-900"
                                                        onClick={() => {
                                                          setExtractRequest({
                                                            projektId,
                                                            runId: String(activeRun?.id || ""),
                                                            pdfDocId: String(pdfDoc.id),
                                                            sectionDocId: String(section.id),
                                                            chapterId: group.chapterId || undefined,
                                                            pdfId: String(section.pdfId || "") || undefined,
                                                            pdfFilename: section.pdfFilename || pdfDoc.pdfFilename || pdfDoc.pdfLabel,
                                                            storagePath: pdfMeta?.storagePath,
                                                            anchorPage: typeof section.anchorPage === "number" ? section.anchorPage : undefined,
                                                          });
                                                          setExtractOpen(true);
                                                        }}
                                                        title="Preview"
                                                      >
                                                        Preview
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
                          </div>
                          </div>
                        </section>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          </main>
        </div>

        <Dialog
          open={kapitelPickerOpen}
          onOpenChange={(open) => {
            setKapitelPickerOpen(open);
            if (!open) setKapitelFilter("");
          }}
        >
          <DialogContent className="max-h-[92vh] w-[96vw] max-w-[calc(100%-2rem)] gap-0 overflow-hidden border-slate-200 bg-white p-0 shadow-[0_24px_80px_rgba(15,23,42,0.24)] sm:w-[980px] sm:!max-w-[980px] lg:w-[1120px] lg:!max-w-[1120px]">
            <DialogHeader className="border-b border-slate-200 bg-white px-6 py-5">
              <DialogTitle className="text-[20px] tracking-[-0.02em] text-slate-950">Kapitel auswählen</DialogTitle>
              <DialogDescription className="sr-only">
                Wähle ein oder mehrere Kapitel für den PDF-Scan aus.
              </DialogDescription>
            </DialogHeader>

            <div className="border-b border-slate-200 bg-slate-50 px-6 py-3.5">
              <div className="relative min-w-0">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  value={kapitelFilter}
                  onChange={(event) => setKapitelFilter(event.target.value)}
                  placeholder="Kapitel suchen..."
                  className="h-10 border-slate-200 bg-white pl-10 shadow-none"
                />
              </div>
            </div>

            <ScrollArea className="h-[min(74vh,940px)] bg-white">
              <div className="space-y-0.5 px-4 py-3">
                {filteredKapitelRows.map((kapitel) => {
                  const checked = selectedKapitelIdSet.has(kapitel.id);
                  const depth = kapitelDepth(kapitel.nummer);
                  return (
                    <label
                      key={kapitel.id}
                      className={cn(
                        "grid cursor-pointer grid-cols-[20px_auto_minmax(0,1fr)] items-start gap-x-2.5 rounded-[8px] px-3 py-2.5 transition-colors",
                        checked ? "bg-sky-50" : "hover:bg-slate-50"
                      )}
                      style={{ paddingLeft: 12 + depth * 12 }}
                    >
                      <div className="pt-0.5">
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(value) => toggleSelectedKapitel(kapitel.id, Boolean(value))}
                          aria-label={buildKapitelLabel(kapitel)}
                        />
                      </div>
                      <div className="pt-0.5 text-[14px] font-semibold tabular-nums leading-6 text-sky-700">
                        {kapitel.nummer || "–"}
                      </div>
                      <div className="min-w-0 text-[14px] leading-6 text-slate-900">
                        {kapitel.title}
                      </div>
                    </label>
                  );
                })}
                {filteredKapitelRows.length === 0 ? (
                  <div className="px-3 py-6 text-sm text-slate-500">Keine Kapitel passen zur Suche.</div>
                ) : null}
              </div>
            </ScrollArea>

            <DialogFooter className="border-t border-slate-200 bg-slate-50 px-6 py-3 sm:items-center sm:justify-between">
              <div className="text-sm text-slate-500">
                {formatIntDe(selectedKapitelIds.length)} von {formatIntDe(kapitels.length)} ausgewählt
              </div>
              <Button className="h-10 bg-[#1680cd] px-4 shadow-none hover:bg-[#0f76c2]" onClick={() => setKapitelPickerOpen(false)}>
                Fertig
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

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
                    const deleteBlocker = pdfDeleteBlockers.get(pdf.id);
                    const deleteTitle = deleteBlocker
                      ? deleteBlocker.isActive
                        ? `PDF wird im aktiven Scan ${deleteBlocker.runId} verwendet`
                        : `PDF wird von Run ${deleteBlocker.runId} referenziert`
                      : "PDF löschen";
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
                            disabled={isDeleting || previewMode || Boolean(deleteBlocker)}
                            onClick={() => requestDeleteProjectPdf(pdf)}
                            title={deleteTitle}
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
                  Kapitel: <span className="font-medium text-slate-900">{formatIntDe(selectedKapitelIds.length)}</span>
                </span>
                <span className="block">
                  PDFs: <span className="font-medium text-slate-900">{formatIntDe(selectedPdfIds.length)}</span>
                </span>
                {selectedKapitelRows.length > 0 ? (
                  <span className="mt-2 block text-xs text-slate-500">
                    {selectedKapitelRows
                      .slice(0, 4)
                      .map((kapitel) => `${kapitel.nummer ? `${kapitel.nummer} ` : ""}${kapitel.title}`)
                      .join(" · ")}
                    {selectedKapitelRows.length > 4 ? ` · +${formatIntDe(selectedKapitelRows.length - 4)} weitere` : ""}
                  </span>
                ) : null}
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

        <AlertDialog
          open={duplicateKapitelConfirmOpen}
          onOpenChange={(open) => {
            setDuplicateKapitelConfirmOpen(open);
            if (!open) setDuplicateKapitelConflictRunId(null);
          }}
        >
          <AlertDialogContent className="max-w-[560px] rounded-[14px] border-slate-200 shadow-xl">
            <AlertDialogHeader>
              <AlertDialogTitle>Für dieses Kapitel läuft bereits ein Scan</AlertDialogTitle>
              <AlertDialogDescription className="text-left text-sm leading-6 text-slate-600">
                <span className="block">
                  Für mindestens eines der ausgewählten Kapitel läuft bereits
                  {selectedKapitelRunningRuns.length > 1 ? ` ${formatIntDe(selectedKapitelRunningRuns.length)} aktive Scans` : " ein aktiver Scan"}
                  {duplicateKapitelPromptRunId ? ` (${duplicateKapitelPromptRunId})` : ""}.
                </span>
                <span className="mt-3 block">
                  Wenn du jetzt noch einen weiteren Scan startest, laufen mehrere PDF-Scans parallel für dasselbe Kapitel.
                </span>
                <span className="mt-3 block font-medium text-slate-900">
                  Bist du wirklich wirklich wirklich sicher, dass du noch einen weiteren Scan starten willst?
                </span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel className="rounded-[4px]">Abbrechen</AlertDialogCancel>
              <AlertDialogAction
                className="rounded-[4px] border-[#1680cd] bg-[#1680cd] text-white hover:bg-[#0f76c2]"
                onClick={() => void confirmStartPdfScan(true)}
              >
                Ja, weiteren Scan starten
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
    </PdfScanAccessGate>
  );
}
