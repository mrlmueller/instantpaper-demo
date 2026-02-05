"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Cookies from "js-cookie";
import { ExternalLink, Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { getDownloadUrlFromStorage } from "@/app/lib/firebase/storage";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";
const DEBUG = process.env.NODE_ENV !== "production";

function qfLog(message: string, data?: Record<string, unknown>) {
  if (!DEBUG) return;
  try {
    // eslint-disable-next-line no-console
    console.info(`[QF/pdf] ${message}`, data ?? {});
  } catch {
    // ignore
  }
}

type PdfExtractStage = "stage2" | "stage3";

export type PdfExtractRequest = {
  projektId: string;
  runId: string;
  stage: PdfExtractStage;
  docId: string;
  pdfId?: string;
  pdfFilename?: string;
  storagePath?: string;
  anchorPage?: number;
};

type HighlightRect = {
  x0n: number;
  y0n: number;
  x1n: number;
  y1n: number;
};

type HighlightPage = {
  page: number;
  rects: HighlightRect[];
};

type PdfExtractResponse = {
  pdf: { id: string; filename: string; storage_path: string | null; size?: number | null } | null;
  hit: { anchor: string; anchor_alt: string; locator_hint: string | null } | null;
  extract: {
    ok: boolean;
    reason?: string;
    detail?: string;
    method?: string;
    section_title?: string | null;
    section_level?: number | null;
    anchor_page?: number;
    anchor_used?: "anchor" | "anchor_alt";
    ambiguous?: boolean;
    tied_candidates?: number;
    tied_pages?: number[];
    start?: { page: number; y: number };
    end?: { page: number; y: number } | null;
    highlights?: { truncated?: boolean; pages?: HighlightPage[] };
  };
  meta?: Record<string, unknown> | null;
};

type PdfJsModule = typeof import("pdfjs-dist");
type PdfViewerModule = typeof import("pdfjs-dist/web/pdf_viewer.mjs");

let pdfjsPromise: Promise<PdfJsModule> | null = null;
let pdfViewerPromise: Promise<PdfViewerModule> | null = null;

function loadPdfJs(): Promise<PdfJsModule> {
  if (!pdfjsPromise) pdfjsPromise = import("pdfjs-dist") as Promise<PdfJsModule>;
  return pdfjsPromise;
}

function loadPdfViewer(): Promise<PdfViewerModule> {
  if (!pdfViewerPromise)
    pdfViewerPromise = (async () => {
      const pdfjs = await loadPdfJs();
      try {
        const g = globalThis as unknown as { pdfjsLib?: unknown };
        if (!g.pdfjsLib) g.pdfjsLib = pdfjs;
      } catch {
        // ignore
      }
      return (await import("pdfjs-dist/web/pdf_viewer.mjs")) as PdfViewerModule;
    })();
  return pdfViewerPromise;
}

function useObservedWidth<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!node) return;
    const update = () => setWidth(node.clientWidth || 0);
    update();
    const ro = new ResizeObserver(() => update());
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);

  return { ref: setNode, width };
}

function useInView(opts: { root: HTMLElement | null; rootMargin?: string }) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    if (!node) return;
    const obs = new IntersectionObserver(
      (entries) => {
        const e = entries[0];
        if (e?.isIntersecting) setInView(true);
      },
      { root: opts.root ?? null, rootMargin: opts.rootMargin ?? "800px 0px" }
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, [node, opts.root, opts.rootMargin]);

  return { ref: setNode, inView };
}

function safeNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function ensurePdfJsWorker(pdfjs: PdfJsModule) {
  const anyPdf = pdfjs as unknown as { GlobalWorkerOptions?: { workerSrc?: string } };
  if (!anyPdf.GlobalWorkerOptions) return;
  if (anyPdf.GlobalWorkerOptions.workerSrc) return;
  anyPdf.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
}

function shortName(filename: string): string {
  const base = String(filename || "").trim();
  if (!base) return "document.pdf";
  if (base.length <= 42) return base;
  return `${base.slice(0, 16)}…${base.slice(-22)}`;
}

function PdfPageCanvas(props: {
  pdf: import("pdfjs-dist").PDFDocumentProxy;
  pageNumber: number;
  targetWidth: number;
  root: HTMLElement | null;
  highlightRects: HighlightRect[];
}) {
  const { pdf, pageNumber, targetWidth, root, highlightRects } = props;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textLayerHostRef = useRef<HTMLDivElement | null>(null);
  const textLayerBuilderRef = useRef<unknown>(null);
  const [dims, setDims] = useState<{ width: number; height: number } | null>(null);
  const { ref, inView } = useInView({ root, rootMargin: "1200px 0px" });

  useEffect(() => {
    if (!inView) return;
    if (!targetWidth) return;
    let cancelled = false;
    let renderTask: { cancel?: () => void; promise?: Promise<unknown> } | null = null;

    (async () => {
      const page = await pdf.getPage(pageNumber);
      const unscaled = page.getViewport({ scale: 1 });
      const scale = targetWidth / unscaled.width;
      const viewport = page.getViewport({ scale });

      if (cancelled) return;
      setDims({ width: viewport.width, height: viewport.height });

      const canvas = canvasRef.current;
      if (!canvas) return;

      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;

      renderTask = page.render({ canvas, viewport });
      try {
        await renderTask.promise;
      } finally {
        // ignore
      }

      const host = textLayerHostRef.current;
      if (!host) return;

      const viewer = await loadPdfViewer();
      const { TextLayerBuilder } = viewer;
      let builder: any = textLayerBuilderRef.current;
      if (!builder || typeof builder.render !== "function" || !builder.div) {
        builder = new TextLayerBuilder({ pdfPage: page, enablePermissions: false });
        textLayerBuilderRef.current = builder;
      }
      const div = builder?.div as HTMLDivElement | undefined;
      if (div) {
        try {
          div.style.setProperty("--user-unit", "1");
          div.style.setProperty("--total-scale-factor", String(viewport.scale));
          div.style.setProperty("--scale-round-x", "1px");
          div.style.setProperty("--scale-round-y", "1px");
        } catch {
          // ignore
        }
      }
      if (div && !host.contains(div)) host.replaceChildren(div);
      await (builder.render as (args: any) => Promise<void>)({ viewport });
    })().catch((err: unknown) => {
      if (cancelled) return;
      console.error("PDF page render failed:", err);
    });

    return () => {
      cancelled = true;
      try {
        renderTask?.cancel?.();
      } catch {
        // ignore
      }
    };
  }, [inView, pdf, pageNumber, targetWidth]);

  useEffect(() => {
    return () => {
      const builder = textLayerBuilderRef.current as { cancel?: () => void } | null;
      try {
        builder?.cancel?.();
      } catch {
        // ignore
      }
    };
  }, []);

  return (
    <div ref={ref} className="flex justify-center">
      <div className="relative qf-pdf-page" style={dims ? { width: dims.width, height: dims.height } : undefined}>
        <canvas ref={canvasRef} className="relative z-0 block bg-white shadow-sm rounded-md" />
        <div ref={textLayerHostRef} className="absolute inset-0 z-10" />
        {dims ? (
          <div className="pointer-events-none absolute inset-0 z-5">
            {highlightRects.map((r, idx) => {
              const left = Math.max(0, Math.min(1, safeNumber(r.x0n) ?? 0)) * dims.width;
              const top = Math.max(0, Math.min(1, safeNumber(r.y0n) ?? 0)) * dims.height;
              const right = Math.max(0, Math.min(1, safeNumber(r.x1n) ?? 0)) * dims.width;
              const bottom = Math.max(0, Math.min(1, safeNumber(r.y1n) ?? 0)) * dims.height;
              const width = Math.max(0, right - left);
              const height = Math.max(0, bottom - top);
              if (!width || !height) return null;
              return (
                <div
                  key={`${pageNumber}_${idx}`}
                  className="absolute rounded-[2px] bg-yellow-200/40 outline outline-1 outline-yellow-500/40"
                  style={{ left, top, width, height }}
                />
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function PdfExtractDialog(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: PdfExtractRequest | null;
}) {
  const { open, onOpenChange, request } = props;

  const [extractResp, setExtractResp] = useState<PdfExtractResponse | null>(null);
  const [loadingExtract, setLoadingExtract] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfErrorToShow, setPdfErrorToShow] = useState<string | null>(null);
  const [pdfDoc, setPdfDoc] = useState<import("pdfjs-dist").PDFDocumentProxy | null>(null);

  const scrollRootRef = useRef<HTMLDivElement | null>(null);
  const { ref: pageWidthRef, width: pageWidth } = useObservedWidth<HTMLDivElement>();

  const effectivePdfId = request?.pdfId || extractResp?.pdf?.id || null;

  const highlightsByPage = useMemo(() => {
    const m = new Map<number, HighlightRect[]>();
    const pages = extractResp?.extract?.highlights?.pages ?? [];
    for (const p of pages) {
      const pno = typeof p.page === "number" ? p.page : null;
      if (!pno) continue;
      const rects = Array.isArray(p.rects) ? p.rects : [];
      m.set(pno, rects);
    }
    return m;
  }, [extractResp]);

  useEffect(() => {
    if (!open) return;
    if (!request) return;

    let cancelled = false;
    const extractController = new AbortController();
    qfLog("dialog open", { request });
    setExtractResp(null);
    setPdfDoc(null);
    setLoadingExtract(true);
    setLoadingPdf(false);
    setExtractError(null);
    setPdfError(null);
    setPdfErrorToShow(null);

    (async () => {
      const token = Cookies.get("__session");
      if (!token) throw new Error("Session token missing.");

      void loadPdfJs().catch(() => undefined);
      void loadPdfViewer().catch(() => undefined);

      qfLog("extract request start", { projektId: request.projektId, runId: request.runId, stage: request.stage, docId: request.docId });
      const res = await fetch(`${API_BASE_URL}/api/quellen-finder/pdf-extract`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        signal: extractController.signal,
        body: JSON.stringify({
          projekt_id: request.projektId,
          run_id: request.runId,
          stage: request.stage,
          doc_id: request.docId,
        }),
      });

      const data = (await res.json().catch(() => null)) as PdfExtractResponse | null;
      if (!res.ok) {
        const detail = (data as unknown as { detail?: unknown })?.detail;
        const msg = typeof detail === "string" ? detail : "Request failed.";
        qfLog("extract request failed", { status: res.status, msg });
        throw new Error(msg);
      }

      if (cancelled) return;
      qfLog("extract request done", {
        ok: Boolean(data?.extract?.ok),
        reason: data?.extract?.reason,
        pdfId: data?.pdf?.id,
        hasStoragePath: Boolean(data?.pdf?.storage_path),
        meta: (data?.meta as Record<string, unknown>) ?? null,
      });
      setExtractResp(data);
      setLoadingExtract(false);
    })()
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadingExtract(false);
        if (err instanceof DOMException && err.name === "AbortError") return;
        const msg = err instanceof Error ? err.message : String(err);
        qfLog("extract request exception", { msg });
        setExtractError(msg);
      });

    return () => {
      cancelled = true;
      extractController.abort();
    };
  }, [open, request]);

  useEffect(() => {
    if (!open) {
      setPdfErrorToShow(null);
      return;
    }
    if (!pdfError) {
      setPdfErrorToShow(null);
      return;
    }
    const t = window.setTimeout(() => setPdfErrorToShow(pdfError), 500);
    return () => window.clearTimeout(t);
  }, [open, pdfError]);

  useEffect(() => {
    if (!open) return;
    if (!request?.projektId) return;
    const pdfId = effectivePdfId;
    if (!pdfId) return;

    let cancelled = false;
    const pdfController = new AbortController();

    setLoadingPdf(true);
    setPdfDoc(null);
    setPdfError(null);

    (async () => {
      const token = Cookies.get("__session");
      if (!token) throw new Error("Session token missing.");

      const url = new URL(`${API_BASE_URL}/api/quellen-finder/project-pdf`);
      url.searchParams.set("projekt_id", request.projektId);
      url.searchParams.set("pdf_id", pdfId);

      qfLog("pdf fetch start", { projektId: request.projektId, pdfId });
      const res = await fetch(url.toString(), {
        headers: { Authorization: `Bearer ${token}` },
        signal: pdfController.signal,
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        qfLog("pdf fetch failed", { status: res.status, detail: detail.slice(0, 200) });
        throw new Error(`PDF fetch failed (${res.status})`);
      }
      const buf = await res.arrayBuffer();
      qfLog("pdf fetch done", { bytes: buf.byteLength, contentType: res.headers.get("content-type") || null });

      const pdfjs = await loadPdfJs();
      ensurePdfJsWorker(pdfjs);

      const loadingTask = pdfjs.getDocument({ data: buf });
      const doc = await loadingTask.promise;

      if (cancelled) {
        try {
          await loadingTask.destroy();
        } catch {
          // ignore
        }
        return;
      }

      setPdfDoc(doc);
      setLoadingPdf(false);
    })().catch((err: unknown) => {
      if (cancelled) return;
      setLoadingPdf(false);
      if (err instanceof DOMException && err.name === "AbortError") return;
      console.error("PDF load failed:", err);
      qfLog("pdf load exception", { msg: err instanceof Error ? err.message : String(err) });
      const msg = err instanceof Error ? err.message : String(err);
      setPdfError(msg);
    });

    return () => {
      cancelled = true;
      pdfController.abort();
    };
  }, [open, request?.projektId, effectivePdfId]);

  useEffect(() => {
    if (!open) return;
    const p = extractResp?.extract?.anchor_page ?? extractResp?.extract?.start?.page ?? request?.anchorPage ?? null;
    if (!pdfDoc || !p) return;
    const root = scrollRootRef.current;
    if (!root) return;

    const el = root.querySelector(`[data-qf-page='${p}']`);
    if (el instanceof HTMLElement) {
      el.scrollIntoView({ block: "start" });
    }
  }, [open, pdfDoc, extractResp?.extract?.anchor_page, extractResp?.extract?.start?.page, request?.anchorPage]);

  const storagePath = request?.storagePath || extractResp?.pdf?.storage_path || null;
  const titleRaw = request?.pdfFilename || extractResp?.pdf?.filename || "PDF Preview";
  const title = shortName(titleRaw);
  const subtitle = loadingExtract
    ? "Extracting highlights…"
    : extractError
      ? `Highlights error: ${extractError}`
      : extractResp?.extract?.ok
        ? `${extractResp.extract.method || "ok"} • p.${extractResp.extract.anchor_page ?? "?"} • section: ${extractResp.extract.section_title || "—"}`
        : extractResp?.extract?.reason
          ? `No highlights (${extractResp.extract.reason})`
          : "No highlights";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[96vw] max-w-[96vw] h-[92vh] p-4" showCloseButton={false}>
        <DialogHeader className="space-y-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <DialogTitle className="truncate" title={titleRaw}>
                {title}
              </DialogTitle>
              <DialogDescription className="truncate">{subtitle}</DialogDescription>
            </div>
            <div className="shrink-0 flex items-center gap-2">
              <Button
                size="icon"
                variant="outline"
                disabled={!storagePath}
                onClick={() =>
                  void (async () => {
                    const path = String(storagePath || "").trim();
                    if (!path) return;
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
                      opened.location.href = url;
                    } catch (e) {
                      try {
                        opened.close();
                      } catch {
                        // ignore
                      }
                      toast.error("PDF konnte nicht geöffnet werden", { description: e instanceof Error ? e.message : String(e) });
                    }
                  })()
                }
                title="Open PDF in new tab"
              >
                <ExternalLink className="h-4 w-4" />
              </Button>
              <DialogClose asChild>
                <Button size="icon" variant="outline" title="Close">
                  <X className="h-4 w-4" />
                </Button>
              </DialogClose>
            </div>
          </div>
        </DialogHeader>

        <div className="mt-2 grid grid-cols-1 lg:grid-cols-[1fr] gap-3 min-h-0 h-full">
          <div className="border border-border rounded-md min-h-0 h-full overflow-hidden">
            <div ref={scrollRootRef} className="h-full overflow-auto bg-muted/20">
              <div ref={pageWidthRef} className="mx-auto w-full max-w-[1100px] p-4 space-y-6">
                {loadingExtract || loadingPdf ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {loadingPdf ? "Loading PDF…" : "Extracting highlights…"}
                  </div>
                ) : null}

                {pdfDoc ? (
                  Array.from({ length: pdfDoc.numPages }, (_, i) => i + 1).map((pno) => (
                    <div key={pno} data-qf-page={pno} className="space-y-2">
                      <div className="text-xs text-muted-foreground">Page {pno}</div>
                      <PdfPageCanvas
                        pdf={pdfDoc}
                        pageNumber={pno}
                        targetWidth={Math.max(320, Math.min(1100, pageWidth || 900))}
                        root={scrollRootRef.current}
                        highlightRects={highlightsByPage.get(pno) ?? []}
                      />
                    </div>
                  ))
                ) : pdfErrorToShow ? (
                  <div className="text-sm text-destructive">PDF konnte nicht geladen werden: {pdfErrorToShow}</div>
                ) : !loadingPdf && !loadingExtract && (request?.pdfId || extractResp?.pdf?.id) ? (
                  <div className="text-sm text-muted-foreground">PDF not loaded yet.</div>
                ) : null}
              </div>
            </div>
          </div>
        </div>

        <style jsx global>{`
          .qf-pdf-page .textLayer {
            position: absolute;
            inset: 0;
            overflow: clip;
            opacity: 1;
            line-height: 1;
            -webkit-text-size-adjust: none;
            -moz-text-size-adjust: none;
            text-size-adjust: none;
            transform-origin: 0 0;
            user-select: text;
            pointer-events: auto;
            cursor: text;
          }
          .qf-pdf-page .textLayer :is(span, br) {
            color: transparent;
            position: absolute;
            white-space: pre;
            transform-origin: 0% 0%;
            cursor: text;
          }
          .qf-pdf-page .textLayer {
            --min-font-size: 1;
            --text-scale-factor: calc(var(--total-scale-factor, 1) * var(--min-font-size, 1));
            --min-font-size-inv: calc(1 / var(--min-font-size, 1));
          }
          .qf-pdf-page .textLayer > :not(.markedContent),
          .qf-pdf-page .textLayer .markedContent span:not(.markedContent) {
            z-index: 1;
            --font-height: 0;
            font-size: calc(var(--text-scale-factor) * var(--font-height));
            --scale-x: 1;
            --rotate: 0deg;
            transform: rotate(var(--rotate)) scaleX(var(--scale-x)) scale(var(--min-font-size-inv));
          }
          .qf-pdf-page .textLayer .markedContent {
            display: contents;
          }
          .qf-pdf-page .textLayer ::selection {
            background: rgba(59, 130, 246, 0.35);
          }
          .qf-pdf-page .textLayer .endOfContent {
            display: block;
            position: absolute;
            inset: 100% 0 0;
            z-index: 0;
            cursor: default;
            user-select: none;
          }
        `}</style>
      </DialogContent>
    </Dialog>
  );
}
