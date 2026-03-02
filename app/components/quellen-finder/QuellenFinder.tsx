"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Cookies from "js-cookie";
import { ArrowLeft, Download, ExternalLink, Eye, Loader2, Search, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { addDoc, deleteDoc, limit, onSnapshot, orderBy, query, serverTimestamp, type CollectionReference } from "firebase/firestore";
import { deleteObject, getStorage, ref, uploadBytes } from "firebase/storage";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { firebaseApp } from "@/app/lib/firebase/config";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { downloadFileFromStorage, getDownloadUrlFromStorage } from "@/app/lib/firebase/storage";
import {
  projectPdfDoc,
  projectPdfsCol,
  projectResearchRunsCol,
  quellenFinderPdfStage2Col,
  quellenFinderPdfStage3Col,
  quellenFinderTwoLaneResultsCol,
  quellenFinderTwoLaneTelemetryCol,
} from "@/app/lib/firestore/refs";
import type {
  PdfScanStage2HitDoc,
  PdfScanStage3SectionDoc,
  ProjectPdfDoc,
  QuellenFinderRunDoc,
  TwoLaneLane,
  TwoLaneResultDoc,
} from "@/app/lib/firestore/types";
import type { Kapitel } from "@/app/actions/kapitels";
import { PdfExtractDialog, type PdfExtractRequest } from "./PdfExtractDialog";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type WithId<T> = T & { id: string };
type WithDocId<T> = T & { docId: string };
type RunRow = WithId<QuellenFinderRunDoc>;
type PdfRow = WithId<ProjectPdfDoc>;
type TwoLaneRow = WithDocId<TwoLaneResultDoc>;
type TelemetryRow = WithId<Record<string, unknown>>;
type Stage2Row = WithId<PdfScanStage2HitDoc>;
type Stage3Row = WithId<PdfScanStage3SectionDoc>;

type SortDir = "asc" | "desc";
type TwoLaneSortKey = "rank" | "laneScore" | "llmScore" | "year" | "citations";

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

function formatDurationMs(ms: number): string {
  const s = Math.max(0, Math.floor(Number(ms) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
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
  const [activeTwoLaneRunId, setActiveTwoLaneRunId] = useState<string | null>(null);
  const [activePdfRunId, setActivePdfRunId] = useState<string | null>(null);

  const [pdfs, setPdfs] = useState<PdfRow[]>([]);
  const [selectedPdfIds, setSelectedPdfIds] = useState<Set<string>>(new Set());
  const [pdfQuery, setPdfQuery] = useState("");
  const [uploadingPdfs, setUploadingPdfs] = useState(false);

  type PlannerModel = "gpt-5-nano" | "gpt-5-mini" | "gpt-5.2";
  type RerankModel = "gpt-5-nano" | "gpt-5-mini";
  type ReasoningEffort = "low" | "medium" | "high";

  const [plannerModel, setPlannerModel] = useState<PlannerModel>("gpt-5-mini");
  const [openalexQueryModel, setOpenalexQueryModel] = useState<PlannerModel>("gpt-5-mini");
  const [s2QueryModel, setS2QueryModel] = useState<PlannerModel>("gpt-5-mini");
  const [rerankModel, setRerankModel] = useState<RerankModel>("gpt-5-nano");
  const [embeddingModel, setEmbeddingModel] = useState("text-embedding-3-small");
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>("high");
  const [rerankConcurrency, setRerankConcurrency] = useState<number>(20);

  const [twoLaneLane, setTwoLaneLane] = useState<TwoLaneLane>("match");
  const [showWithoutAbstract, setShowWithoutAbstract] = useState(false);

  const [twoLaneResults, setTwoLaneResults] = useState<TwoLaneRow[]>([]);
  const [twoLaneTelemetry, setTwoLaneTelemetry] = useState<TelemetryRow[]>([]);

  const [resultsQuery, setResultsQuery] = useState("");
  const [resultsSortKey, setResultsSortKey] = useState<TwoLaneSortKey>("rank");
  const [resultsSortDir, setResultsSortDir] = useState<SortDir>("asc");

  const [paperDialogOpen, setPaperDialogOpen] = useState(false);
  const [activePaper, setActivePaper] = useState<TwoLaneRow | null>(null);
  const [telemetryDialogOpen, setTelemetryDialogOpen] = useState(false);
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const [extractDialogOpen, setExtractDialogOpen] = useState(false);
  const [extractRequest, setExtractRequest] = useState<PdfExtractRequest | null>(null);

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

  const pdfById = useMemo(() => {
    const map = new Map<string, PdfRow>();
    for (const p of pdfs) map.set(p.id, p);
    return map;
  }, [pdfs]);

  const filteredPdfs = useMemo(() => {
    const q = pdfQuery.trim().toLowerCase();
    if (!q) return pdfs;
    return pdfs.filter((p) => {
      const name = String(p.filename || "").toLowerCase();
      const path = String(p.storagePath || "").toLowerCase();
      return name.includes(q) || path.includes(q) || p.id.toLowerCase().includes(q);
    });
  }, [pdfQuery, pdfs]);

  const twoLaneRuns = useMemo(() => runs.filter((r) => r.kind === "sources_two_lane"), [runs]);
  const pdfRuns = useMemo(() => runs.filter((r) => r.kind === "pdf_scan"), [runs]);

  const activeTwoLaneRun = useMemo(() => {
    if (!activeTwoLaneRunId) return twoLaneRuns[0] ?? null;
    return twoLaneRuns.find((r) => r.id === activeTwoLaneRunId) ?? twoLaneRuns[0] ?? null;
  }, [twoLaneRuns, activeTwoLaneRunId]);

  const activePdfRun = useMemo(() => {
    if (!activePdfRunId) return pdfRuns[0] ?? null;
    return pdfRuns.find((r) => r.id === activePdfRunId) ?? pdfRuns[0] ?? null;
  }, [pdfRuns, activePdfRunId]);

  useEffect(() => {
    if (!activeTwoLaneRunId && twoLaneRuns.length) setActiveTwoLaneRunId(twoLaneRuns[0].id);
    if (activeTwoLaneRunId && !twoLaneRuns.some((r) => r.id === activeTwoLaneRunId)) {
      setActiveTwoLaneRunId(twoLaneRuns[0]?.id ?? null);
    }
  }, [twoLaneRuns, activeTwoLaneRunId]);

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
    if (!user?.uid || !projektId || !activeTwoLaneRun?.id) {
      setTwoLaneResults([]);
      setTwoLaneTelemetry([]);
      return;
    }

    const resultsCol = quellenFinderTwoLaneResultsCol(firestoreClient, user.uid, projektId, activeTwoLaneRun.id);
    const telemetryCol = quellenFinderTwoLaneTelemetryCol(firestoreClient, user.uid, projektId, activeTwoLaneRun.id);

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

    const unsubTelemetry = onSnapshot(
      query(telemetryCol, limit(200)),
      (snap) => {
        const next = snap.docs.map((d) => ({ id: d.id, ...(d.data() as Record<string, unknown>) }));
        setTwoLaneTelemetry(next);
      },
      (err) => {
        console.error("Failed to load twoLaneTelemetry:", err);
        setTwoLaneTelemetry([]);
      }
    );

    return () => {
      unsubResults();
      unsubTelemetry();
    };
  }, [user?.uid, projektId, activeTwoLaneRun?.id]);

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

  const telemetryById = useMemo(() => {
    const map = new Map<string, TelemetryRow>();
    for (const t of twoLaneTelemetry) map.set(t.id, t);
    return map;
  }, [twoLaneTelemetry]);

  const finalReportView = useMemo(() => {
    const fr = telemetryById.get("final_report") as Record<string, unknown> | undefined;
    const frRec: Record<string, unknown> = fr && typeof fr === "object" ? fr : {};

    const models = (frRec["models"] && typeof frRec["models"] === "object" ? (frRec["models"] as Record<string, unknown>) : {}) as Record<string, unknown>;

    const summary = activeTwoLaneRun?.summary;
    const summaryRec: Record<string, unknown> = summary && typeof summary === "object" ? (summary as Record<string, unknown>) : {};
    const costsFromFinalReport = frRec["costs"] && typeof frRec["costs"] === "object" ? (frRec["costs"] as Record<string, unknown>) : null;
    const costs = (costsFromFinalReport ?? summaryRec) as Record<string, unknown>;

    const stageCosts =
      costs["stage_costs"] && typeof costs["stage_costs"] === "object" ? (costs["stage_costs"] as Record<string, unknown>) : ({} as Record<string, unknown>);
    const durations =
      frRec["durations_s"] && typeof frRec["durations_s"] === "object" ? (frRec["durations_s"] as Record<string, unknown>) : ({} as Record<string, unknown>);
    const counts = (frRec["counts"] && typeof frRec["counts"] === "object" ? (frRec["counts"] as Record<string, unknown>) : {}) as Record<string, unknown>;

    const stageRows = Object.entries(stageCosts).map(([stage, v]) => {
      const rec = v && typeof v === "object" ? (v as Record<string, unknown>) : ({} as Record<string, unknown>);
      const costUsd = typeof rec["cost_usd"] === "number" && Number.isFinite(rec["cost_usd"]) ? (rec["cost_usd"] as number) : null;
      const inputTokens = typeof rec["input_tokens"] === "number" ? (rec["input_tokens"] as number) : null;
      const outputTokens = typeof rec["output_tokens"] === "number" ? (rec["output_tokens"] as number) : null;
      const requests = typeof rec["requests"] === "number" ? (rec["requests"] as number) : null;
      const durationS = typeof durations[stage] === "number" && Number.isFinite(durations[stage]) ? (durations[stage] as number) : null;
      return { stage, costUsd, inputTokens, outputTokens, requests, durationS };
    });
    stageRows.sort((a, b) => (b.costUsd ?? -1) - (a.costUsd ?? -1));

    const totalCostUsd = typeof costs["total_cost_usd"] === "number" ? (costs["total_cost_usd"] as number) : null;
    const budgetCapUsd = typeof costs["budget_cap_usd"] === "number" ? (costs["budget_cap_usd"] as number) : null;
    const keySource = typeof costs["key_source"] === "string" ? (costs["key_source"] as string) : null;

    return { models, costs, stageRows, counts, totalCostUsd, budgetCapUsd, keySource, raw: fr ? frRec : { costs: summaryRec } };
  }, [telemetryById, activeTwoLaneRun?.summary]);

  const twoLaneFiltered = useMemo(() => {
    const q = resultsQuery.trim().toLowerCase();

    let rows = twoLaneResults.filter(
      (r) => r.lane === twoLaneLane && (r.pool === "with_abstract" || (showWithoutAbstract && r.pool === "without_abstract"))
    );

    if (q) {
      rows = rows.filter((r) => {
        const title = String(r.title || "").toLowerCase();
        const authors = Array.isArray(r.authors) ? r.authors.join("; ").toLowerCase() : "";
        const venue = String(r.venue || "").toLowerCase();
        const doi = String(r.doi || "").toLowerCase();
        return title.includes(q) || authors.includes(q) || venue.includes(q) || doi.includes(q);
      });
    }

    const dir = resultsSortDir === "asc" ? 1 : -1;
    const byNum = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : -Infinity);
    const byRank = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 9999);

    const laneScore = (r: TwoLaneRow) => {
      const s = r.scores || ({} as Record<string, unknown>);
      const key = twoLaneLane === "match" ? "match_lane" : "authority_lane";
      const v = (s as Record<string, unknown>)[key];
      return byNum(typeof v === "number" ? v : null);
    };

    const llmScore = (r: TwoLaneRow) => {
      const v = (r.rerank as Record<string, unknown> | null | undefined)?.llm_score_0_100;
      return byNum(typeof v === "number" ? v : null);
    };

    return [...rows].sort((a, b) => {
      if (resultsSortKey === "rank") return dir * (byRank(a.rank) - byRank(b.rank));
      if (resultsSortKey === "year") return dir * (byNum(a.year) - byNum(b.year));
      if (resultsSortKey === "citations") return dir * (byNum(a.citations) - byNum(b.citations));
      if (resultsSortKey === "llmScore") return dir * (llmScore(a) - llmScore(b));
      return dir * (laneScore(a) - laneScore(b));
    });
  }, [twoLaneResults, twoLaneLane, showWithoutAbstract, resultsQuery, resultsSortDir, resultsSortKey]);

  const canRunTwoLane = Boolean(user?.uid && projektId && selectedKapitelIds.length === 1);
  const canRunPdfScan = Boolean(user?.uid && projektId && selectedKapitelIds.length === 1 && selectedPdfIds.size > 0);

  const runningTwoLane = activeTwoLaneRun?.status === "running" || activeTwoLaneRun?.status === "queued";
  const runningPdfScan = activePdfRun?.status === "running" || activePdfRun?.status === "queued";

  useEffect(() => {
    if (!runningTwoLane) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [runningTwoLane]);

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

  const openPdfInNewTab = async (storagePath: string, opts?: { page?: number }) => {
    const path = String(storagePath || "").trim();
    if (!path) {
      toast.error("PDF kann nicht geöffnet werden", { description: "Storage-Pfad fehlt." });
      return;
    }

    const opened = window.open("about:blank", "_blank");
    if (!opened) {
      toast.error("PDF kann nicht geöffnet werden", { description: "Popup blockiert." });
      return;
    }
    try {
      opened.opener = null;
    } catch {
      // ignore
    }

    try {
      const url = await getDownloadUrlFromStorage(path);
      const finalUrl = opts?.page ? `${url}#page=${opts.page}` : url;
      opened.location.href = finalUrl;
    } catch (e) {
      try {
        opened.close();
      } catch {
        // ignore
      }
      toast.error("PDF konnte nicht geöffnet werden", { description: e instanceof Error ? e.message : String(e) });
    }
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

  const startTwoLaneSources = async () => {
    if (!canRunTwoLane) {
      toast.error("Bitte genau ein Kapitel auswählen.");
      return;
    }
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }
    const kapitelId = selectedKapitelIds[0];

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/sources-two-lane/start`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
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
      toast.error("Two-Lane Sources fehlgeschlagen", { description: detail });
      return;
    }

    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const runId = typeof data.run_id === "string" ? String(data.run_id) : "";
    if (runId) setActiveTwoLaneRunId(runId);
    toast.success("Two-Lane Sources gestartet", { description: runId ? `Run: ${runId}` : undefined });
  };

  const retryTwoLaneSources = async () => {
    if (!activeTwoLaneRun?.id) {
      toast.error("Kein aktiver Run", { description: "Bitte zuerst einen Run auswählen." });
      return;
    }
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }

    const kapitelId = activeTwoLaneRun.kapitelIds?.[0] || selectedKapitelIds[0] || "";
    if (!kapitelId) {
      toast.error("Kapitel fehlt", { description: "Der Run hat keine Kapitel-ID." });
      return;
    }

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/sources-two-lane/start`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        projekt_id: projektId,
        kapitel_id: kapitelId,
        resume_run_id: activeTwoLaneRun.id,
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
      toast.error("Retry fehlgeschlagen", { description: detail });
      return;
    }

    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const runId = typeof data.run_id === "string" ? String(data.run_id) : "";
    if (runId) setActiveTwoLaneRunId(runId);
    toast.success("Retry gestartet", { description: runId ? `Run: ${runId}` : undefined });
  };

  const cancelTwoLaneSources = async () => {
    if (!activeTwoLaneRun?.id) {
      toast.error("Kein aktiver Run", { description: "Bitte zuerst einen Run auswählen." });
      return;
    }
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/sources-two-lane/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ projekt_id: projektId, run_id: activeTwoLaneRun.id }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      toast.error("Cancel fehlgeschlagen", { description: detail });
      return;
    }

    toast.success("Cancellation requested", { description: `Run: ${activeTwoLaneRun.id}` });
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

  const openExtractDialog = (args: {
    stage: "stage2" | "stage3";
    docId: string;
    pdfId?: string;
    pdfFilename?: string;
    storagePath?: string;
    anchorPage?: number;
  }) => {
    if (!activePdfRun?.id) {
      toast.error("Kein aktiver PDF-Run", { description: "Bitte zuerst einen PDF-Run auswählen." });
      return;
    }
    setExtractRequest({
      projektId,
      runId: activePdfRun.id,
      stage: args.stage,
      docId: args.docId,
      pdfId: args.pdfId,
      pdfFilename: args.pdfFilename,
      storagePath: args.storagePath,
      anchorPage: args.anchorPage,
    });
    setExtractDialogOpen(true);
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
          <div className="lg:sticky lg:top-4 self-start">
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
                          <Checkbox checked={checked} onClick={(e) => e.stopPropagation()} onCheckedChange={() => toggleKapitel(k.id)} />
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
          </div>

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
                  <div className="text-sm font-semibold">1) Sources (Two-lane)</div>
                  <div className="text-xs text-muted-foreground">
                    Match/Authority × With/Without Abstract. Speichert Top-40 pro Lane/Pool + Telemetry (Firestore).
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap justify-end">
                  <Button size="sm" variant="outline" onClick={() => setSettingsDialogOpen(true)}>
                    Settings
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setTelemetryDialogOpen(true)} disabled={!activeTwoLaneRun?.id}>
                    Run details
                  </Button>
                  {activeTwoLaneRun?.id && (activeTwoLaneRun.status === "error" || activeTwoLaneRun.status === "cancelled") ? (
                    <Button size="sm" variant="outline" onClick={retryTwoLaneSources} disabled={runningTwoLane}>
                      Retry
                    </Button>
                  ) : null}
                  <Button size="sm" onClick={startTwoLaneSources} disabled={!canRunTwoLane || runningTwoLane}>
                    {runningTwoLane ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                    Start
                  </Button>
                  <Button size="sm" variant="destructive" onClick={cancelTwoLaneSources} disabled={!runningTwoLane}>
                    Cancel
                  </Button>
                </div>
              </div>

              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <div className="text-xs text-muted-foreground">Run:</div>
                <Select value={activeTwoLaneRun?.id || ""} onValueChange={(v) => setActiveTwoLaneRunId(v || null)} disabled={twoLaneRuns.length === 0}>
                  <SelectTrigger className="w-[320px] h-8">
                    <SelectValue placeholder="(keine Runs)" />
                  </SelectTrigger>
                  <SelectContent>
                    {twoLaneRuns.map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {formatRunTime(r.createdAt) || r.id} — {r.status}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {activeTwoLaneRun ? (
                  <>
                    <Badge variant={statusBadgeVariant(activeTwoLaneRun.status)}>{activeTwoLaneRun.status}</Badge>
                    {activeTwoLaneRun.hadPartialFailures ? <Badge variant="outline">partial</Badge> : null}
                    <span className="text-xs text-muted-foreground">{progressLabel(activeTwoLaneRun)}</span>
                  </>
                ) : null}
                {activeTwoLaneRun ? (
                  <div className="ml-auto flex items-center gap-2 flex-wrap justify-end">
                    {runningTwoLane ? (
                      <>
                        <Badge variant="outline" className="tabular-nums">
                          Elapsed {formatDurationMs(nowMs - (toDateOrNull(activeTwoLaneRun.startedAt) ?? toDateOrNull(activeTwoLaneRun.createdAt) ?? new Date()).getTime())}
                        </Badge>
                        <Badge variant="outline" className="tabular-nums">
                          Stage{" "}
                          {formatDurationMs(
                            nowMs -
                              (toDateOrNull(activeTwoLaneRun.progress?.stageStartedAt) ??
                                toDateOrNull(activeTwoLaneRun.startedAt) ??
                                toDateOrNull(activeTwoLaneRun.createdAt) ??
                                new Date()).getTime()
                          )}
                        </Badge>
                      </>
                    ) : null}
                    {typeof (activeTwoLaneRun.summary as Record<string, unknown> | undefined)?.total_cost_usd === "number" ? (
                      <Badge variant="secondary" className="tabular-nums">
                        ${Number((activeTwoLaneRun.summary as Record<string, unknown>).total_cost_usd).toFixed(2)}
                      </Badge>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <Separator className="my-3" />

              <div className="flex items-center gap-2 flex-wrap">
                <Tabs
                  value={twoLaneLane}
                  onValueChange={(v) => {
                    if (v === "match" || v === "authority") setTwoLaneLane(v as TwoLaneLane);
                  }}
                >
                  <TabsList className="h-8">
                    <TabsTrigger value="match" className="text-xs">
                      Match
                    </TabsTrigger>
                    <TabsTrigger value="authority" className="text-xs">
                      Authority
                    </TabsTrigger>
                  </TabsList>
                </Tabs>

                <div className="flex items-center gap-2">
                  <Switch id="qf-show-without-abstract" checked={showWithoutAbstract} onCheckedChange={setShowWithoutAbstract} />
                  <Label htmlFor="qf-show-without-abstract" className="text-xs text-muted-foreground cursor-pointer">
                    Show without abstract (display only)
                  </Label>
                </div>

                <div className="flex items-center gap-2 flex-1 min-w-[220px]">
                  <Search className="h-4 w-4 text-muted-foreground" />
                  <Input value={resultsQuery} onChange={(e) => setResultsQuery(e.target.value)} placeholder="Filter: title/authors/venue/doi" className="h-8" />
                </div>

                <Select
                  value={resultsSortKey}
                  onValueChange={(v) => {
                    if (v === "rank" || v === "laneScore" || v === "llmScore" || v === "year" || v === "citations") setResultsSortKey(v);
                  }}
                >
                  <SelectTrigger className="w-[170px] h-8">
                    <SelectValue placeholder="Sort" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="rank">Rank</SelectItem>
                    <SelectItem value="laneScore">Lane score</SelectItem>
                    <SelectItem value="llmScore">LLM score</SelectItem>
                    <SelectItem value="citations">Citations</SelectItem>
                    <SelectItem value="year">Year</SelectItem>
                  </SelectContent>
                </Select>

                <Select value={resultsSortDir} onValueChange={(v) => (v === "asc" || v === "desc" ? setResultsSortDir(v) : null)}>
                  <SelectTrigger className="w-[120px] h-8">
                    <SelectValue placeholder="Dir" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="asc">Asc</SelectItem>
                    <SelectItem value="desc">Desc</SelectItem>
                  </SelectContent>
                </Select>

                <div className="text-xs text-muted-foreground">
                  Rows: <span className="font-medium">{twoLaneFiltered.length}</span>
                </div>
              </div>

              <div className="mt-3 md:hidden space-y-2">
                {twoLaneFiltered.map((r) => {
                  const s = r.scores || ({} as Record<string, unknown>);
                  const laneScore =
                    typeof (s as Record<string, unknown>)[twoLaneLane === "match" ? "match_lane" : "authority_lane"] === "number"
                      ? (s as Record<string, unknown>)[twoLaneLane === "match" ? "match_lane" : "authority_lane"]
                      : null;
                  const llmScore = (r.rerank as Record<string, unknown> | null | undefined)?.llm_score_0_100;
                  const insuff = Boolean((r.rerank as Record<string, unknown> | null | undefined)?.insufficient_info);
                  return (
                    <button
                      key={r.docId}
                      type="button"
                      className="w-full text-left rounded-md border border-border hover:bg-muted/40 transition-colors px-3 py-2"
                      onClick={() => {
                        setActivePaper(r);
                        setPaperDialogOpen(true);
                      }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium line-clamp-2">{r.title || "(untitled)"}</div>
                          <div className="text-xs text-muted-foreground line-clamp-1">
                            {(r.authors || []).slice(0, 4).join(", ")}
                            {r.year ? ` • ${r.year}` : ""}
                            {typeof r.citations === "number" ? ` • cites ${r.citations}` : ""}
                            {r.pool === "without_abstract" ? " • no abstract" : ""}
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-1 shrink-0">
                          <div className="text-xs tabular-nums">{typeof laneScore === "number" ? laneScore.toFixed(3) : ""}</div>
                          <div className="flex items-center gap-1">
                            {typeof llmScore === "number" ? <Badge variant="secondary">LLM {llmScore}</Badge> : null}
                            {insuff ? <Badge variant="outline">insuff</Badge> : null}
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
                {twoLaneFiltered.length === 0 ? <div className="text-sm text-muted-foreground">Keine Ergebnisse.</div> : null}
              </div>

              <div className="mt-3 hidden md:block overflow-x-auto border border-border rounded-md">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[64px]">#</TableHead>
                      <TableHead>Title</TableHead>
                      <TableHead className="w-[80px] hidden lg:table-cell">Year</TableHead>
                      <TableHead className="w-[90px] hidden lg:table-cell">Cites</TableHead>
                      <TableHead className="w-[110px]">Lane</TableHead>
                      <TableHead className="w-[110px]">LLM</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {twoLaneFiltered.map((r) => {
                      const s = r.scores || ({} as Record<string, unknown>);
                      const laneScore =
                        typeof (s as Record<string, unknown>)[twoLaneLane === "match" ? "match_lane" : "authority_lane"] === "number"
                          ? (s as Record<string, unknown>)[twoLaneLane === "match" ? "match_lane" : "authority_lane"]
                          : null;
                      const llmScore = (r.rerank as Record<string, unknown> | null | undefined)?.llm_score_0_100;
                      const insuff = Boolean((r.rerank as Record<string, unknown> | null | undefined)?.insufficient_info);
                      return (
                        <TableRow
                          key={r.docId}
                          className="cursor-pointer"
                          onClick={() => {
                            setActivePaper(r);
                            setPaperDialogOpen(true);
                          }}
                        >
                          <TableCell className="tabular-nums">{r.rank}</TableCell>
                          <TableCell className="min-w-[360px]">
                            <div className="font-medium line-clamp-2">{r.title || "(untitled)"}</div>
                            <div className="text-xs text-muted-foreground line-clamp-1">
                              {(r.authors || []).slice(0, 6).join(", ")}
                              {r.venue ? ` • ${r.venue}` : ""}
                              {r.doi ? ` • DOI: ${r.doi}` : ""}
                              {r.pool === "without_abstract" ? " • no abstract" : ""}
                            </div>
                          </TableCell>
                          <TableCell className="tabular-nums hidden lg:table-cell">{r.year ?? ""}</TableCell>
                          <TableCell className="tabular-nums hidden lg:table-cell">{r.citations ?? ""}</TableCell>
                          <TableCell className="tabular-nums">{typeof laneScore === "number" ? laneScore.toFixed(3) : ""}</TableCell>
                          <TableCell className="tabular-nums">
                            <div className="flex items-center gap-1">
                              {typeof llmScore === "number" ? <Badge variant="secondary">{llmScore}</Badge> : <span className="text-muted-foreground">—</span>}
                              {insuff ? <Badge variant="outline">insuff</Badge> : null}
                            </div>
                          </TableCell>
                        </TableRow>
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

              <Dialog open={paperDialogOpen} onOpenChange={setPaperDialogOpen}>
                <DialogContent className="max-w-3xl">
                  <DialogHeader>
                    <DialogTitle>{activePaper?.title || "Paper"}</DialogTitle>
                  </DialogHeader>
                  <div className="max-h-[70vh] overflow-auto space-y-4">
                    <div className="text-xs text-muted-foreground">
                      {(activePaper?.authors || []).slice(0, 12).join(", ")}
                      {activePaper?.year ? ` • ${activePaper.year}` : ""}
                      {activePaper?.venue ? ` • ${activePaper.venue}` : ""}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {activePaper?.url ? (
                        <Button asChild size="sm" variant="outline">
                          <Link href={activePaper.url} target="_blank" rel="noreferrer">
                            <ExternalLink className="h-4 w-4 mr-2" />
                            Open
                          </Link>
                        </Button>
                      ) : null}
                      {activePaper?.doi ? (
                        <Badge variant="outline" className="font-mono">
                          DOI: {activePaper.doi}
                        </Badge>
                      ) : null}
                      {typeof activePaper?.citations === "number" ? <Badge variant="outline">cites {activePaper.citations}</Badge> : null}
                      {typeof activePaper?.influential_citations === "number" ? <Badge variant="outline">infl {activePaper.influential_citations}</Badge> : null}
                    </div>

                    <div className="space-y-1">
                      <div className="text-sm font-medium">Abstract</div>
                      <div className="text-xs text-muted-foreground whitespace-pre-wrap">{activePaper?.abstract || "(none)"}</div>
                    </div>

                    <div className="space-y-1">
                      <div className="text-sm font-medium">Scores</div>
                      <pre className="text-xs overflow-auto whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">{JSON.stringify(activePaper?.scores ?? {}, null, 2)}</pre>
                    </div>

                    <div className="space-y-1">
                      <div className="text-sm font-medium">Rerank</div>
                      <pre className="text-xs overflow-auto whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">{JSON.stringify(activePaper?.rerank ?? null, null, 2)}</pre>
                    </div>

                    <div className="space-y-1">
                      <div className="text-sm font-medium">Coverage tags</div>
                      <pre className="text-xs overflow-auto whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">{JSON.stringify(activePaper?.coverage_tags ?? [], null, 2)}</pre>
                    </div>

                    <div className="space-y-1">
                      <div className="text-sm font-medium">Debug</div>
                      <pre className="text-xs overflow-auto whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(
                          {
                            provider: activePaper?.provider ?? null,
                            provider_ids: activePaper?.provider_ids ?? null,
                            external_ids: activePaper?.external_ids ?? null,
                            sources: activePaper?.sources ?? null,
                          },
                          null,
                          2
                        )}
                      </pre>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>

              <Dialog open={telemetryDialogOpen} onOpenChange={setTelemetryDialogOpen}>
                <DialogContent className="max-w-5xl">
                  <DialogHeader>
                    <DialogTitle>Two-lane run details</DialogTitle>
                  </DialogHeader>
                  <Tabs defaultValue="overview">
                    <TabsList className="h-8 flex flex-wrap">
                      <TabsTrigger value="overview" className="text-xs">
                        Overview
                      </TabsTrigger>
                      <TabsTrigger value="facets" className="text-xs">
                        Facets
                      </TabsTrigger>
                      <TabsTrigger value="queries" className="text-xs">
                        Queries
                      </TabsTrigger>
                      <TabsTrigger value="retrieval" className="text-xs">
                        Retrieval
                      </TabsTrigger>
                      <TabsTrigger value="candidates" className="text-xs">
                        Candidates
                      </TabsTrigger>
                      <TabsTrigger value="scoring" className="text-xs">
                        Scoring
                      </TabsTrigger>
                      <TabsTrigger value="rerank" className="text-xs">
                        Rerank
                      </TabsTrigger>
                      <TabsTrigger value="metrics" className="text-xs">
                        Metrics
                      </TabsTrigger>
                    </TabsList>

                    <TabsContent value="overview" className="mt-3">
                      <div className="space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          <div className="rounded-md border border-border p-3">
                            <div className="text-xs text-muted-foreground">Total cost</div>
                            <div className="text-sm font-medium tabular-nums">
                              {typeof finalReportView.totalCostUsd === "number" ? `$${finalReportView.totalCostUsd.toFixed(2)}` : "—"}
                              {typeof finalReportView.budgetCapUsd === "number" ? (
                                <span className="text-xs text-muted-foreground"> / ${finalReportView.budgetCapUsd.toFixed(2)} cap</span>
                              ) : null}
                            </div>
                          </div>
                          <div className="rounded-md border border-border p-3">
                            <div className="text-xs text-muted-foreground">Key source</div>
                            <div className="text-sm font-medium">{finalReportView.keySource || "—"}</div>
                          </div>
                          <div className="rounded-md border border-border p-3">
                            <div className="text-xs text-muted-foreground">Candidates</div>
                            <div className="text-sm font-medium tabular-nums">
                              {typeof finalReportView.counts["candidates_total"] === "number" ? String(finalReportView.counts["candidates_total"]) : "—"}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              OA recs:{" "}
                              <span className="tabular-nums">
                                {typeof finalReportView.counts["records_openalex"] === "number" ? String(finalReportView.counts["records_openalex"]) : "—"}
                              </span>{" "}
                              • S2 recs:{" "}
                              <span className="tabular-nums">
                                {typeof finalReportView.counts["records_semanticscholar"] === "number"
                                  ? String(finalReportView.counts["records_semanticscholar"])
                                  : "—"}
                              </span>
                            </div>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div className="rounded-md border border-border p-3">
                            <div className="text-sm font-medium mb-2">Models</div>
                            <div className="text-xs text-muted-foreground space-y-1">
                              <div>
                                Planner: <span className="font-medium text-foreground">{String(finalReportView.models["planner"] ?? "—")}</span>
                              </div>
                              <div>
                                OpenAlex queries:{" "}
                                <span className="font-medium text-foreground">{String(finalReportView.models["openalex_query_builder"] ?? "—")}</span>
                              </div>
                              <div>
                                S2 queries: <span className="font-medium text-foreground">{String(finalReportView.models["s2_query_builder"] ?? "—")}</span>
                              </div>
                              <div>
                                Rerank: <span className="font-medium text-foreground">{String(finalReportView.models["rerank"] ?? "—")}</span>
                              </div>
                              <div>
                                Embedding: <span className="font-medium text-foreground">{String(finalReportView.models["embedding"] ?? "—")}</span>
                              </div>
                            </div>
                          </div>

                          <div className="rounded-md border border-border p-3">
                            <div className="text-sm font-medium mb-2">Queries</div>
                            <div className="text-xs text-muted-foreground space-y-1">
                              <div>
                                OpenAlex:{" "}
                                <span className="font-medium text-foreground tabular-nums">
                                  {typeof finalReportView.counts["queries_openalex"] === "number" ? String(finalReportView.counts["queries_openalex"]) : "—"}
                                </span>
                              </div>
                              <div>
                                Semantic Scholar:{" "}
                                <span className="font-medium text-foreground tabular-nums">
                                  {typeof finalReportView.counts["queries_semanticscholar"] === "number"
                                    ? String(finalReportView.counts["queries_semanticscholar"])
                                    : "—"}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-md border border-border overflow-x-auto">
                          <div className="px-3 py-2 border-b border-border">
                            <div className="text-sm font-medium">Cost & time by stage</div>
                          </div>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>Stage</TableHead>
                                <TableHead className="w-[110px]">Cost</TableHead>
                                <TableHead className="w-[90px] hidden lg:table-cell">Requests</TableHead>
                                <TableHead className="w-[110px] hidden lg:table-cell">In tokens</TableHead>
                                <TableHead className="w-[110px] hidden lg:table-cell">Out tokens</TableHead>
                                <TableHead className="w-[110px]">Seconds</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {finalReportView.stageRows.map((r) => (
                                <TableRow key={r.stage}>
                                  <TableCell className="font-mono text-xs">{r.stage}</TableCell>
                                  <TableCell className="tabular-nums">{typeof r.costUsd === "number" ? `$${r.costUsd.toFixed(4)}` : "—"}</TableCell>
                                  <TableCell className="tabular-nums hidden lg:table-cell">{typeof r.requests === "number" ? r.requests : "—"}</TableCell>
                                  <TableCell className="tabular-nums hidden lg:table-cell">{typeof r.inputTokens === "number" ? r.inputTokens : "—"}</TableCell>
                                  <TableCell className="tabular-nums hidden lg:table-cell">{typeof r.outputTokens === "number" ? r.outputTokens : "—"}</TableCell>
                                  <TableCell className="tabular-nums">{typeof r.durationS === "number" ? Math.round(r.durationS) : "—"}</TableCell>
                                </TableRow>
                              ))}
                              {finalReportView.stageRows.length === 0 ? (
                                <TableRow>
                                  <TableCell colSpan={6} className="text-sm text-muted-foreground">
                                    No stage breakdown available.
                                  </TableCell>
                                </TableRow>
                              ) : null}
                            </TableBody>
                          </Table>
                        </div>

                        <details>
                          <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                          <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                            {JSON.stringify(finalReportView.raw ?? {}, null, 2)}
                          </pre>
                        </details>
                      </div>
                    </TabsContent>
                    <TabsContent value="facets" className="mt-3">
                      <pre className="text-xs overflow-auto max-h-[65vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(telemetryById.get("phase_b_plan") ?? {}, null, 2)}
                      </pre>
                    </TabsContent>
                    <TabsContent value="queries" className="mt-3">
                      <pre className="text-xs overflow-auto max-h-[65vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(telemetryById.get("phase_c_queries") ?? {}, null, 2)}
                      </pre>
                    </TabsContent>
                    <TabsContent value="retrieval" className="mt-3">
                      <pre className="text-xs overflow-auto max-h-[65vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(telemetryById.get("phase_d_retrieval") ?? {}, null, 2)}
                      </pre>
                    </TabsContent>
                    <TabsContent value="candidates" className="mt-3">
                      <pre className="text-xs overflow-auto max-h-[65vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(telemetryById.get("phase_e_candidates") ?? {}, null, 2)}
                      </pre>
                    </TabsContent>
                    <TabsContent value="scoring" className="mt-3">
                      <pre className="text-xs overflow-auto max-h-[65vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(telemetryById.get("phase_f_scoring") ?? {}, null, 2)}
                      </pre>
                    </TabsContent>
                    <TabsContent value="rerank" className="mt-3">
                      <pre className="text-xs overflow-auto max-h-[65vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(telemetryById.get("phase_i_rerank") ?? {}, null, 2)}
                      </pre>
                    </TabsContent>
                    <TabsContent value="metrics" className="mt-3">
                      <pre className="text-xs overflow-auto max-h-[65vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                        {JSON.stringify(telemetryById.get("metrics") ?? {}, null, 2)}
                      </pre>
                    </TabsContent>
                  </Tabs>
                </DialogContent>
              </Dialog>

              <Dialog open={settingsDialogOpen} onOpenChange={setSettingsDialogOpen}>
                <DialogContent className="max-w-2xl">
                  <DialogHeader>
                    <DialogTitle>Two-lane settings</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <div className="text-xs text-muted-foreground">Planner model</div>
                        <Select value={plannerModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.2" ? setPlannerModel(v) : null)}>
                          <SelectTrigger className="h-8">
                            <SelectValue placeholder="Planner" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                            <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                            <SelectItem value="gpt-5.2">gpt-5.2</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-1">
                        <div className="text-xs text-muted-foreground">OpenAlex query model</div>
                        <Select value={openalexQueryModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.2" ? setOpenalexQueryModel(v) : null)}>
                          <SelectTrigger className="h-8">
                            <SelectValue placeholder="OpenAlex" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                            <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                            <SelectItem value="gpt-5.2">gpt-5.2</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-1">
                        <div className="text-xs text-muted-foreground">S2 query model</div>
                        <Select value={s2QueryModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.2" ? setS2QueryModel(v) : null)}>
                          <SelectTrigger className="h-8">
                            <SelectValue placeholder="S2" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                            <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                            <SelectItem value="gpt-5.2">gpt-5.2</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-1">
                        <div className="text-xs text-muted-foreground">Rerank model</div>
                        <Select value={rerankModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" ? setRerankModel(v) : null)}>
                          <SelectTrigger className="h-8">
                            <SelectValue placeholder="Rerank" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                            <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-1">
                        <div className="text-xs text-muted-foreground">Reasoning effort</div>
                        <Select value={reasoningEffort} onValueChange={(v) => (v === "low" || v === "medium" || v === "high" ? setReasoningEffort(v) : null)}>
                          <SelectTrigger className="h-8">
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
                          className="h-8"
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
                      <Input className="h-8" value={embeddingModel} onChange={(e) => setEmbeddingModel(e.target.value)} placeholder="text-embedding-3-small" />
                    </div>

                    <div className="text-xs text-muted-foreground">Budget cap is enforced server-side (2 USD). Rerank disallows gpt-5.2.</div>
                  </div>
                </DialogContent>
              </Dialog>
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
                  <div className="flex items-center gap-2 mb-2">
                    <Search className="h-4 w-4 text-muted-foreground" />
                    <Input value={pdfQuery} onChange={(e) => setPdfQuery(e.target.value)} placeholder="PDF suchen (Name/Path/ID)" />
                  </div>
                  <div className="text-xs text-muted-foreground mb-2">
                    Ausgewählt: <span className="font-medium">{selectedPdfIds.size}</span> PDFs • Insgesamt: <span className="font-medium">{pdfs.length}</span>
                  </div>
                  <div className="space-y-2 max-h-[320px] overflow-auto pr-1">
                    {filteredPdfs.map((p) => {
                      const checked = selectedPdfIds.has(p.id);
                      return (
                        <div key={p.id} className="flex items-start gap-2 rounded-md border border-border px-3 py-2 hover:bg-muted/40 transition-colors">
                          <div className="pt-0.5">
                            <Checkbox checked={checked} onCheckedChange={() => togglePdf(p.id)} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-sm font-medium truncate min-w-0" title={`${p.filename}\n${p.storagePath}`}>
                                {p.filename}
                              </div>
                              <div className="text-xs text-muted-foreground tabular-nums shrink-0">
                                {(Number(p.size || 0) / (1024 * 1024)).toFixed(1)} MB
                              </div>
                            </div>
                            <div className="text-[11px] text-muted-foreground truncate">Uploaded: {formatRunTime(p.createdAt)}</div>
                          </div>
                          <div className="flex items-center gap-1">
                            <Button size="icon" variant="ghost" onClick={() => void openPdfInNewTab(String(p.storagePath || ""))} title="Open (Browser)">
                              <ExternalLink className="h-4 w-4" />
                            </Button>
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
                    {filteredPdfs.length === 0 ? (
                      <div className="text-sm text-muted-foreground">{pdfs.length === 0 ? "Noch keine PDFs hochgeladen." : "Keine PDFs gefunden."}</div>
                    ) : null}
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
                              <TableHead className="w-[200px]">PDF</TableHead>
                              <TableHead>Section</TableHead>
                              <TableHead className="w-[80px]">Score</TableHead>
                              <TableHead className="w-[380px]">Why</TableHead>
                              <TableHead className="w-[360px]">Anchor</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {stage3.map((r) => {
                              const pdf = pdfById.get(String(r.pdfId || ""));
                              const storagePath = String(pdf?.storagePath || "");
                              const pdfId = String(r.pdfId || "").trim();
                              const pdfLabel = String(r.pdfLabel || pdf?.filename || "");
                              const page = typeof r.anchorPage === "number" ? r.anchorPage : undefined;
                              return (
                                <TableRow key={r.id}>
                                  <TableCell className="min-w-[200px]">
                                    <div className="flex items-start gap-2">
                                      <div className="min-w-0">
                                        <div className="text-sm font-medium truncate" title={pdfLabel}>
                                          {pdfLabel}
                                        </div>
                                        <div className="text-[11px] text-muted-foreground">
                                          {r.anchorPage ? `p. ${r.anchorPage}` : null}
                                          {r.hitCount ? (r.anchorPage ? ` • hits ${r.hitCount}` : `hits ${r.hitCount}`) : null}
                                        </div>
                                      </div>
                                      <div className="shrink-0 flex items-center gap-1">
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          onClick={() =>
                                            openExtractDialog({
                                              stage: "stage3",
                                              docId: r.id,
                                              pdfId: pdfId || undefined,
                                              pdfFilename: pdfLabel,
                                              storagePath: storagePath || undefined,
                                              anchorPage: page,
                                            })
                                          }
                                          title="Preview highlights"
                                        >
                                          <Eye className="h-4 w-4" />
                                        </Button>
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          disabled={!storagePath}
                                          onClick={() => void openPdfInNewTab(storagePath, { page })}
                                          title={storagePath ? "Open PDF" : "PDF fehlt in Library"}
                                        >
                                          <ExternalLink className="h-4 w-4" />
                                        </Button>
                                      </div>
                                    </div>
                                  </TableCell>
                                  <TableCell className="min-w-[240px]">
                                    <div className="text-sm font-medium">{r.heading || ""}</div>
                                    <div className="text-xs text-muted-foreground whitespace-pre-wrap line-clamp-2">{(r.coveredSubpoints || []).join(", ")}</div>
                                  </TableCell>
                                  <TableCell className="tabular-nums">{r.score ?? ""}</TableCell>
                                  <TableCell className="min-w-[380px]">
                                    <div className="text-xs whitespace-pre-wrap line-clamp-4">{r.summary || ""}</div>
                                  </TableCell>
                                  <TableCell className="min-w-[360px]">
                                    <div className="text-xs whitespace-pre-wrap line-clamp-4">{r.anchor || ""}</div>
                                  </TableCell>
                                </TableRow>
                              );
                            })}
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
                              <TableHead className="w-[200px]">PDF</TableHead>
                              <TableHead className="w-[80px]">Score</TableHead>
                              <TableHead className="w-[160px]">Subpoint</TableHead>
                              <TableHead className="w-[380px]">Why</TableHead>
                              <TableHead className="w-[360px]">Evidence</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {stage2.map((r) => {
                              const pdf = pdfById.get(String(r.pdfId || ""));
                              const storagePath = String(pdf?.storagePath || "");
                              const pdfId = String(r.pdfId || "").trim();
                              const pdfLabel = String(r.pdfLabel || pdf?.filename || "");
                              const why = (r.scoreRationale || r.coverage || "").trim();
                              return (
                                <TableRow key={r.id}>
                                  <TableCell className="min-w-[200px]">
                                    <div className="flex items-start gap-2">
                                      <div className="min-w-0">
                                        <div className="text-sm font-medium truncate" title={pdfLabel}>
                                          {pdfLabel}
                                        </div>
                                      </div>
                                      <div className="shrink-0 flex items-center gap-1">
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          onClick={() =>
                                            openExtractDialog({
                                              stage: "stage2",
                                              docId: r.id,
                                              pdfId: pdfId || undefined,
                                              pdfFilename: pdfLabel,
                                              storagePath: storagePath || undefined,
                                            })
                                          }
                                          title="Preview highlights"
                                        >
                                          <Eye className="h-4 w-4" />
                                        </Button>
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          disabled={!storagePath}
                                          onClick={() => void openPdfInNewTab(storagePath)}
                                          title={storagePath ? "Open PDF" : "PDF fehlt in Library"}
                                        >
                                          <ExternalLink className="h-4 w-4" />
                                        </Button>
                                      </div>
                                    </div>
                                  </TableCell>
                                  <TableCell className="tabular-nums">{r.score ?? ""}</TableCell>
                                  <TableCell className="min-w-[160px]">
                                    <div className="text-sm">{r.subpoint || ""}</div>
                                  </TableCell>
                                  <TableCell className="min-w-[380px]">
                                    {why ? <div className="text-xs whitespace-pre-wrap line-clamp-3">{why}</div> : <div className="text-xs text-muted-foreground">—</div>}
                                    {r.summary ? <div className="text-xs text-muted-foreground whitespace-pre-wrap line-clamp-2 mt-1">{r.summary}</div> : null}
                                  </TableCell>
                                  <TableCell className="min-w-[360px]">
                                    <div className="text-xs whitespace-pre-wrap line-clamp-4">{r.anchor || ""}</div>
                                    {r.locatorHint ? <div className="text-xs text-muted-foreground line-clamp-2 mt-1">Locator: {r.locatorHint}</div> : null}
                                  </TableCell>
                                </TableRow>
                              );
                            })}
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
      <PdfExtractDialog
        open={extractDialogOpen}
        onOpenChange={(next) => {
          setExtractDialogOpen(next);
          if (!next) setExtractRequest(null);
        }}
        request={extractRequest}
      />
    </div>
  );
}
