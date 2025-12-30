"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Clock3, Download, XCircle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { getDownloadUrlFromStorage } from "@/app/lib/firebase/storage";
import { cn } from "@/lib/utils";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";

type ExportStatus = "running" | "success" | "error";

type ExportDoc = {
  id: string;
  exportId: string;
  projektId: string;
  projektSnapshot?: { id?: string; name?: string; archived?: boolean } | null;
  selection?: { type?: "all" | "selected"; kapitelCount?: number; kapitelIds?: string[] } | null;
  status: ExportStatus;
  errorMessage?: string | null;
  createdAt?: unknown;
  finishedAt?: unknown;
  expiresAt?: unknown;
  file?: { storagePath?: string; fileName?: string; sizeBytes?: number } | null;
  costUsd?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toExportStatus(value: unknown): ExportStatus {
  return value === "success" || value === "error" || value === "running" ? value : "running";
}

function toSelectionType(value: unknown): "all" | "selected" | undefined {
  return value === "all" || value === "selected" ? value : undefined;
}

function toDate(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (typeof value === "string") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (
    typeof value === "object" &&
    value !== null &&
    "toDate" in value &&
    typeof (value as { toDate?: unknown }).toDate === "function"
  ) {
    const d = (value as { toDate: () => unknown }).toDate();
    return d instanceof Date ? d : null;
  }
  return null;
}

function formatDateTime(value: unknown): string | null {
  const d = toDate(value);
  if (!d) return null;
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatBytes(bytes: number): string {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let idx = 0;
  let size = value;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  return `${size.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function formatUsd(costUsd: unknown): string | null {
  const c = Number(costUsd ?? 0);
  if (!Number.isFinite(c) || c <= 0) return null;
  return `$${c.toFixed(4)}`;
}

function statusMeta(status: ExportStatus) {
  if (status === "success") {
    return { label: "Fertig", icon: CheckCircle2, color: "text-emerald-600" };
  }
  if (status === "error") {
    return { label: "Fehler", icon: XCircle, color: "text-red-600" };
  }
  return { label: "In Bearbeitung", icon: Clock3, color: "text-amber-600" };
}

export function ExportsTab({ userId }: { userId: string }) {
  const [exports, setExports] = useState<ExportDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [downloadUrls, setDownloadUrls] = useState<Record<string, string | null>>({});

  useEffect(() => {
    if (!userId) return;

    setLoading(true);
    const q = query(
      collection(firestoreClient, "users", userId, "exports"),
      orderBy("createdAt", "desc"),
      limit(50)
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const items: ExportDoc[] = snap.docs.map((d) => {
          const raw = d.data() as unknown;
          const data = isRecord(raw) ? raw : {};

          const rawProject = isRecord(data.projektSnapshot) ? data.projektSnapshot : null;
          const projektSnapshot = rawProject
            ? {
                id: typeof rawProject.id === "string" ? rawProject.id : undefined,
                name: typeof rawProject.name === "string" ? rawProject.name : undefined,
                archived: typeof rawProject.archived === "boolean" ? rawProject.archived : undefined,
              }
            : null;

          const rawSelection = isRecord(data.selection) ? data.selection : null;
          const selection = rawSelection
            ? {
                type: toSelectionType(rawSelection.type),
                kapitelCount: Number(rawSelection.kapitelCount ?? 0),
                kapitelIds: Array.isArray(rawSelection.kapitelIds)
                  ? rawSelection.kapitelIds.filter((v): v is string => typeof v === "string")
                  : undefined,
              }
            : null;

          const rawFile = isRecord(data.file) ? data.file : null;
          const file = rawFile
            ? {
                storagePath: typeof rawFile.storagePath === "string" ? rawFile.storagePath : undefined,
                fileName: typeof rawFile.fileName === "string" ? rawFile.fileName : undefined,
                sizeBytes: Number(rawFile.sizeBytes ?? 0),
              }
            : null;

          return {
            id: d.id,
            exportId: typeof data.exportId === "string" ? data.exportId : d.id,
            projektId: typeof data.projektId === "string" ? data.projektId : "",
            projektSnapshot,
            selection,
            status: toExportStatus(data.status),
            errorMessage: typeof data.errorMessage === "string" ? data.errorMessage : null,
            createdAt: data.createdAt,
            finishedAt: data.finishedAt,
            expiresAt: data.expiresAt,
            file,
            costUsd: Number(data.costUsd ?? 0),
          };
        });

        setExports(items);
        setLoading(false);
      },
      (err) => {
        console.error("Failed to load exports:", err);
        toast.error("Exporte", { description: "Exporte konnten nicht geladen werden." });
        setExports([]);
        setLoading(false);
      }
    );

    return () => {
      unsub();
    };
  }, [userId]);

  useEffect(() => {
    if (loading) return;
    if (exports.length === 0) return;

    const candidates = exports.filter((ex) => {
      if (ex.status !== "success") return false;
      if (!ex.file?.storagePath) return false;
      return downloadUrls[ex.id] === undefined;
    });
    if (candidates.length === 0) return;

    let cancelled = false;

    Promise.all(
      candidates.map(async (ex) => {
        try {
          const url = await getDownloadUrlFromStorage(String(ex.file?.storagePath || ""));
          return [ex.id, url] as const;
        } catch (err) {
          console.error("Failed to get export download URL:", err);
          return [ex.id, null] as const;
        }
      })
    ).then((entries) => {
      if (cancelled) return;
      setDownloadUrls((prev) => {
        const next = { ...prev };
        for (const [id, url] of entries) next[id] = url;
        return next;
      });
    });

    return () => {
      cancelled = true;
    };
  }, [downloadUrls, exports, loading]);

  const content = useMemo(() => {
    if (loading) {
      return (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <Card key={i} className="p-6">
              <div className="flex items-start justify-between gap-6">
                <div className="flex-1">
                  <Skeleton className="h-5 w-64 mb-3" />
                  <Skeleton className="h-4 w-56 mb-1.5" />
                  <Skeleton className="h-4 w-44" />
                </div>
                <Skeleton className="h-10 w-28" />
              </div>
            </Card>
          ))}
        </div>
      );
    }

    if (exports.length === 0) {
      return (
        <Card className="p-6">
          <p className="text-sm text-muted-foreground">Noch keine Exporte vorhanden.</p>
        </Card>
      );
    }

    return (
      <div className="space-y-3">
        {exports.map((ex) => {
          const projectName = String(ex.projektSnapshot?.name || "Projekt");
          const selectionType = ex.selection?.type === "all" ? "Ganzes Projekt" : `${ex.selection?.kapitelCount ?? 0} Kapitel`;
          const created = formatDateTime(ex.createdAt);
          const finished = formatDateTime(ex.finishedAt);
          const expires = formatDateTime(ex.expiresAt);
          const fileSize = ex.file?.sizeBytes ? formatBytes(ex.file.sizeBytes) : null;
          const cost = formatUsd(ex.costUsd);

          const meta = statusMeta(ex.status);
          const StatusIcon = meta.icon;

          const downloadUrl = downloadUrls[ex.id];

          return (
            <Card key={ex.id} className="p-6">
              <div className="flex items-start justify-between gap-6">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <StatusIcon className={cn("h-5 w-5", meta.color)} />
                    <h3 className="text-base font-semibold text-foreground truncate max-w-[420px]">{projectName}</h3>
                    <Badge variant="secondary">{selectionType}</Badge>
                  </div>

                  <div className="mt-2 text-sm text-muted-foreground space-y-0.5">
                    {created && <div>Erstellt: {created}</div>}
                    {ex.status === "success" && finished && (
                      <div>
                        Fertig: {finished}
                        {fileSize ? ` · ${fileSize}` : ""}
                        {cost ? ` · ${cost}` : ""}
                      </div>
                    )}
                    {ex.status === "running" && <div>{meta.label}…</div>}
                    {ex.status === "error" && (
                      <div className="text-red-600">Fehler beim Erstellen der Datei{ex.errorMessage ? `: ${ex.errorMessage}` : ""}</div>
                    )}
                    {expires && <div className="text-xs">Verfügbar bis: {expires}</div>}
                  </div>

                  <div className="mt-3">
                    <Badge variant="outline" className="text-[11px]">
                      Mit Quellen-Fußnoten
                    </Badge>
                  </div>
                </div>

                <div className="shrink-0">
                  {ex.status === "success" ? (
                    downloadUrl ? (
                      <Button asChild>
                        <a href={downloadUrl} rel="noreferrer">
                          <Download className="h-4 w-4 mr-2" />
                          Download
                        </a>
                      </Button>
                    ) : downloadUrl === null ? (
                      <Button
                        variant="outline"
                        onClick={() => {
                          toast.error("Download nicht verfügbar", {
                            description: "Bitte erstelle den Export erneut.",
                          });
                        }}
                      >
                        Download
                      </Button>
                    ) : (
                      <Button variant="outline" disabled>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Download vorbereiten…
                      </Button>
                    )
                  ) : (
                    <div className={cn("text-sm font-medium", meta.color)}>{meta.label}</div>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    );
  }, [downloadUrls, exports, loading]);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-foreground mb-1">Meine Exporte</h2>
        <p className="text-sm text-muted-foreground">
          Deine Exporte werden im Hintergrund erstellt. Bitte lade sie zeitnah herunter (ca. 7 Tage verfügbar).
        </p>
      </div>

      {content}
    </div>
  );
}
