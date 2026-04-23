"use client";

import type React from "react";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Send,
  ChevronLeft,
  ChevronRight,
  Check,
  X,
  Sparkles,
  FileText,
  Copy,
  Loader2,
  Star,
  Expand,
  CheckCircle2,
  Edit2,
} from "lucide-react";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { AI_GENERIC_ERROR_MESSAGE } from "@/app/lib/ai/messages";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { collection, doc, onSnapshot, updateDoc, serverTimestamp } from "firebase/firestore";
import { createManualShortenedRefinement, createShortenedRefinement, initShortenedRefinement } from "@/app/actions/kapitels";
import { ManualRefinementEditorDialog } from "@/app/components/dashboard/ManualRefinementEditorDialog";

type RefinementVersion = {
  id: string;
  parentVersionId: string | null;
  depth: number;
  userMessage?: string | null;
  assistantText?: string;
  status: "running" | "success" | "error";
  source?: "root" | "ai" | "manual";
  manualEdit?: boolean;
  model?: string;
  usage?: {
    inputTokens: number;
    cachedInputTokens: number;
    outputTokens: number;
    reasoningTokens: number;
    totalTokens: number;
  } | null;
  costUsd?: number; // USD float
  createdAt?: unknown;
  errorMessage?: string;
};

function toDate(value: unknown): Date {
  if (!value) return new Date(0);
  if (typeof value === "string") return new Date(value);
  if (typeof value === "object" && "toDate" in value && typeof (value as { toDate?: unknown }).toDate === "function") {
    return (value as { toDate: () => Date }).toDate();
  }
  return new Date(0);
}

function normalizeVersionStatus(status: unknown): RefinementVersion["status"] {
  return status === "running" || status === "error" || status === "success" ? status : "success";
}

function countWords(text: string) {
  return (text || "").trim().split(/\s+/).filter(Boolean).length;
}

interface ShortenedRefinementDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kapitelId: string;
  runId: string;
  kapitelLabel: string;
  ensureOpenAIAccess: () => Promise<boolean>;
  onAuthFailure: () => void;
  onServerDown: (toastId?: string | number) => void;
  onOpenTextViewer: (content: { title: string; text: string }) => void;
}

export function ShortenedRefinementDialog(_props: ShortenedRefinementDialogProps) {
  const {
    open,
    onOpenChange,
    kapitelId,
    runId,
    kapitelLabel,
    ensureOpenAIAccess,
    onAuthFailure,
    onServerDown,
    onOpenTextViewer,
  } = _props;

  const { user } = useAuth();

  const [initLoading, setInitLoading] = useState(false);
  const [maxDepth, setMaxDepth] = useState<number>(4);
  const [activeVersionId, setActiveVersionId] = useState<string>("root");
  const [refinementCostTotalUsd, setRefinementCostTotalUsd] = useState<number>(0);

  const [versions, setVersions] = useState<RefinementVersion[]>([]);
  const [selectedChildByParentId, setSelectedChildByParentId] = useState<Record<string, string>>({});

  const [editingVersionId, setEditingVersionId] = useState<string | null>(null);
  const [editMessage, setEditMessage] = useState("");
  const [editSending, setEditSending] = useState(false);

  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);

  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [viewingFullText, setViewingFullText] = useState<{ title: string; text: string } | null>(null);
  const [manualEditTarget, setManualEditTarget] = useState<{ version: RefinementVersion; title: string; text: string } | null>(null);
  const [manualSaving, setManualSaving] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const db = useMemo(() => firestoreClient, []);

  const shortenedDocRef = useMemo(() => {
    if (!user?.uid) return null;
    return doc(db, "users", user.uid, "kapitels", kapitelId, "runs", runId, "artifacts", "shortened");
  }, [db, user?.uid, kapitelId, runId]);

  const versionsRef = useMemo(() => {
    if (!shortenedDocRef) return null;
    return collection(shortenedDocRef, "versions");
  }, [shortenedDocRef]);

  useEffect(() => {
    setSelectedChildByParentId({});
    setEditingVersionId(null);
    setEditMessage("");
    setMessage("");
    setManualEditTarget(null);
  }, [kapitelId, runId]);

  useEffect(() => {
    if (open) return;
    setEditingVersionId(null);
    setEditMessage("");
    setEditSending(false);
    setManualEditTarget(null);
    setManualSaving(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (!kapitelId || !runId) return;
    if (!user?.uid) return;
    if (initLoading) return;

    setInitLoading(true);
    initShortenedRefinement(kapitelId, runId)
      .then((res) => {
        if (!res?.success) {
          const msg = (res?.error || "Initialisierung fehlgeschlagen.").toString();
          const lower = msg.toLowerCase();
          if (lower.includes("sitzung")) {
            onAuthFailure();
            return;
          }
          if (lower.includes("fastapi-server")) {
            onServerDown("refine-shortened-init-down");
            return;
          }
          toast.error("Refinement nicht verf\u00fcgbar", { description: msg });
          return;
        }
        const data = (res.data || {}) as { max_depth?: unknown; active_version_id?: unknown };
        setMaxDepth(Number(data.max_depth ?? 4));
        setActiveVersionId(String(data.active_version_id ?? "root"));
      })
      .finally(() => setInitLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kapitelId, runId, user?.uid]);

  useEffect(() => {
    if (!open) return;
    if (!shortenedDocRef) return;

    const unsub = onSnapshot(
      shortenedDocRef,
      (snap) => {
        const data = snap.data() as { refinement?: { activeVersionId?: unknown; costTotalUsd?: unknown } } | undefined;
        if (!data) return;
        setActiveVersionId(String(data.refinement?.activeVersionId ?? "root"));
        setRefinementCostTotalUsd(Number(data.refinement?.costTotalUsd ?? 0));
      },
      (err) => {
        console.error("Shortened refinement doc listen failed:", err);
      }
    );

    return () => unsub();
  }, [open, shortenedDocRef]);

  useEffect(() => {
    if (!open) return;
    if (!versionsRef) return;

    const unsub = onSnapshot(
      versionsRef,
      (snap) => {
        const items: RefinementVersion[] = snap.docs.map((d) => {
          const data = d.data() as Record<string, unknown>;
          const source = data.source === "manual" ? "manual" : d.id === "root" ? "root" : "ai";
          return {
            id: d.id,
            parentVersionId: typeof data.parentVersionId === "string" ? data.parentVersionId : null,
            depth: Number(data.depth ?? 0),
            userMessage: typeof data.userMessage === "string" ? data.userMessage : null,
            assistantText: String(data.assistantText ?? ""),
            status: normalizeVersionStatus(data.status),
            source,
            manualEdit: Boolean(data.manualEdit ?? source === "manual"),
            model: typeof data.model === "string" ? data.model : "",
            usage: data.usage && typeof data.usage === "object" ? (data.usage as RefinementVersion["usage"]) : null,
            costUsd: typeof data.costUsd === "number" ? data.costUsd : Number(data.costUsd ?? 0),
            createdAt: data.createdAt,
            errorMessage: typeof data.errorMessage === "string" ? data.errorMessage : "",
          };
        });
        setVersions(items);
      },
      (err) => {
        console.error("Shortened refinement versions listen failed:", err);
      }
    );

    return () => unsub();
  }, [open, versionsRef]);

  const tree = useMemo(() => {
    const byId = new Map<string, RefinementVersion>(versions.map((v) => [v.id, v]));
    const childrenByParentId = new Map<string, RefinementVersion[]>();

    for (const v of versions) {
      const parentId = v.parentVersionId;
      if (!parentId) continue;
      const arr = childrenByParentId.get(parentId) ?? [];
      arr.push(v);
      childrenByParentId.set(parentId, arr);
    }

    for (const arr of childrenByParentId.values()) {
      arr.sort((a, b) => {
        const ta = toDate(a.createdAt).getTime();
        const tb = toDate(b.createdAt).getTime();
        if (ta !== tb) return ta - tb;
        return a.id.localeCompare(b.id);
      });
    }

    return {
      byId,
      childrenByParentId,
      root: byId.get("root") ?? null,
    };
  }, [versions]);

  const path = useMemo(() => {
    if (!tree.root) return [];

    const chain: RefinementVersion[] = [tree.root];
    let current: RefinementVersion = tree.root;
    let guard = 0;
    while (guard < 32) {
      guard++;
      const children = tree.childrenByParentId.get(current.id) ?? [];
      if (children.length === 0) break;

      const selectedChildId = selectedChildByParentId[current.id];
      const selectedChild = selectedChildId ? tree.byId.get(selectedChildId) : null;
      const next =
        selectedChild && selectedChild.parentVersionId === current.id ? selectedChild : children[children.length - 1];

      chain.push(next);
      current = next;
    }
    return chain;
  }, [tree, selectedChildByParentId]);

  useEffect(() => {
    if (!editingVersionId) return;
    const stillVisible = path.some((v) => v.id === editingVersionId);
    if (stillVisible) return;
    setEditingVersionId(null);
    setEditMessage("");
  }, [editingVersionId, path]);

  const parentForNext = path[path.length - 1] ?? tree.root ?? null;
  const nextDepth = (parentForNext?.depth ?? 0) + 1;
  const isDepthLimitReached = nextDepth > maxDepth;

  const isOptimisticallyWaitingOnSelectedPath = useMemo(() => {
    for (const node of path) {
      const selectedChildId = selectedChildByParentId[node.id];
      if (selectedChildId && !tree.byId.has(selectedChildId)) return true;
    }
    return false;
  }, [path, selectedChildByParentId, tree.byId]);

  const isSelectedBranchRunning = parentForNext?.status === "running" || isOptimisticallyWaitingOnSelectedPath;

  useEffect(() => {
    if (!open) return;
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [open, path.length, parentForNext?.status, parentForNext?.id]);

  const handleUseVersion = useCallback(
    async (version: RefinementVersion) => {
      if (!shortenedDocRef) return;
      if (!version.assistantText || version.status !== "success") return;

      try {
        await updateDoc(shortenedDocRef, {
          content: version.assistantText,
          updatedAt: serverTimestamp(),
          "refinement.activeVersionId": version.id,
          "refinement.selectedAt": serverTimestamp(),
        });
        toast.success("Version \u00fcbernommen", { description: "Der gek\u00fcrzte Text wurde aktualisiert." });
      } catch (err: unknown) {
        console.error("Failed to set active shortened refinement version:", err);
        toast.error("Konnte Version nicht \u00fcbernehmen", {
          description: err instanceof Error ? err.message : "Unbekannter Fehler",
        });
      }
    },
    [shortenedDocRef]
  );

  const handleCopy = useCallback(async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }, []);

  const openManualEditor = useCallback((version: RefinementVersion, title: string, text: string) => {
    if (version.status !== "success" || !text.trim()) return;
    setManualEditTarget({ version, title, text });
  }, []);

  const handleManualSave = useCallback(
    async (text: string) => {
      if (!kapitelId || !runId) return;
      if (!user?.uid) return;
      if (!manualEditTarget) return;

      const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      if (!normalized.trim()) return;

      const parentVersionId = manualEditTarget.version.id || "root";
      setManualSaving(true);
      try {
        const res = await createManualShortenedRefinement(kapitelId, runId, parentVersionId, normalized);
        if (!res?.success) {
          const msg = (res?.error || "Manuelle Änderung konnte nicht gespeichert werden.").toString();
          const lower = msg.toLowerCase();
          if (lower.includes("sitzung")) {
            onAuthFailure();
            return;
          }
          if (lower.includes("fastapi-server")) {
            onServerDown("refine-shortened-manual-down");
            return;
          }
          toast.error("Änderung nicht gespeichert", { description: msg });
          return;
        }

        const responseData = res.data as { version_id?: unknown } | undefined;
        const newVersionId = String(responseData?.version_id ?? "");
        if (newVersionId) {
          setSelectedChildByParentId((prev) => ({ ...prev, [parentVersionId]: newVersionId }));
        }
        setManualEditTarget(null);
        toast.success("Manuelle Änderung gespeichert", {
          description: "Der gekürzte Text wurde aktualisiert.",
        });
      } finally {
        setManualSaving(false);
      }
    },
    [kapitelId, runId, manualEditTarget, onAuthFailure, onServerDown, user?.uid]
  );

  const handleSend = useCallback(async () => {
    if (!kapitelId || !runId) return;
    if (!user?.uid) return;
    const trimmed = message.trim();
    if (!trimmed) return;
    if (sending) return;
    if (isSelectedBranchRunning) return;

    if (!(await ensureOpenAIAccess())) return;

    if (nextDepth > maxDepth) {
      toast.error("Limit erreicht", {
        description: `Maximal ${maxDepth} Iterationen ab Root m\u00f6glich. Bitte w\u00e4hle eine andere Version oder starte neu.`,
      });
      return;
    }

    const parentVersionId = parentForNext?.id || "root";
    setSending(true);
    try {
      const res = await createShortenedRefinement(kapitelId, runId, parentVersionId, trimmed);
      if (!res?.success) {
        const msg = (res?.error || "Refinement konnte nicht gestartet werden.").toString();
        const lower = msg.toLowerCase();
        if (lower.includes("sitzung")) {
          onAuthFailure();
          return;
        }
        if (lower.includes("fastapi-server")) {
          onServerDown("refine-shortened-down");
          return;
        }
        toast.error("Refinement fehlgeschlagen", { description: msg });
        return;
      }

      const responseData = res.data as { version_id?: unknown } | undefined;
      const newVersionId = String(responseData?.version_id ?? "");
      if (newVersionId) {
        setSelectedChildByParentId((prev) => ({ ...prev, [parentVersionId]: newVersionId }));
      }

      setMessage("");
      toast.success("Refinement gestartet", {
        description: `Iteration ${nextDepth}/${maxDepth} wird berechnet...`,
      });
    } finally {
      setSending(false);
    }
  }, [
    ensureOpenAIAccess,
    isSelectedBranchRunning,
    kapitelId,
    maxDepth,
    message,
    nextDepth,
    onAuthFailure,
    onServerDown,
    parentForNext?.id,
    runId,
    sending,
    user?.uid,
  ]);

  const handleCycleBranch = useCallback(
    (parentId: string, delta: -1 | 1) => {
      const children = tree.childrenByParentId.get(parentId) ?? [];
      if (children.length < 2) return;

      setSelectedChildByParentId((prev) => {
        const currentId = prev[parentId];
        let index = currentId ? children.findIndex((c) => c.id === currentId) : -1;
        if (index === -1) index = children.length - 1;
        const nextIndex = (index + delta + children.length) % children.length;
        const nextChild = children[nextIndex];
        return { ...prev, [parentId]: nextChild.id };
      });
    },
    [tree.childrenByParentId]
  );

  const startEdit = useCallback((version: RefinementVersion) => {
    setEditingVersionId(version.id);
    setEditMessage(String(version.userMessage ?? ""));
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingVersionId(null);
    setEditMessage("");
  }, []);

  const submitEdit = useCallback(
    async (version: RefinementVersion) => {
      if (!kapitelId || !runId) return;
      if (!user?.uid) return;
      if (editSending) return;

      const trimmed = editMessage.trim();
      if (!trimmed) return;

      if (!(await ensureOpenAIAccess())) return;

      const parentId = version.parentVersionId || "root";
      const editedDepth = version.depth ?? 1;
      if (editedDepth > maxDepth) {
        toast.error("Limit erreicht", {
          description: `Maximal ${maxDepth} Iterationen ab Root m\u00f6glich. Bitte w\u00e4hle eine andere Version.`,
        });
        return;
      }

      setEditSending(true);
      try {
        const res = await createShortenedRefinement(kapitelId, runId, parentId, trimmed);
        if (!res?.success) {
          const msg = (res?.error || "Refinement konnte nicht gestartet werden.").toString();
          const lower = msg.toLowerCase();
          if (lower.includes("sitzung")) {
            onAuthFailure();
            return;
          }
          if (lower.includes("fastapi-server")) {
            onServerDown("refine-shortened-down");
            return;
          }
          toast.error("Refinement fehlgeschlagen", { description: msg });
          return;
        }

        const responseData = res.data as { version_id?: unknown } | undefined;
        const newVersionId = String(responseData?.version_id ?? "");
        if (newVersionId) {
          setSelectedChildByParentId((prev) => ({ ...prev, [parentId]: newVersionId }));
        }

        cancelEdit();
        toast.success("Branch erstellt", {
          description: "Die ge\u00e4nderte Nachricht wurde als neuer Branch gespeichert.",
        });
      } finally {
        setEditSending(false);
      }
    },
    [
      cancelEdit,
      editMessage,
      editSending,
      ensureOpenAIAccess,
      kapitelId,
      maxDepth,
      onAuthFailure,
      onServerDown,
      runId,
      user?.uid,
    ]
  );

  const PREVIEW_LENGTH = 300;

  const originalText = (tree.root?.assistantText || "").toString();
  const isOriginalActive = activeVersionId === "root";

  const userMessageCount = Math.max(0, path.length - 1);
  const canSendMore = userMessageCount < maxDepth;
  const roundsRemaining = Math.max(0, maxDepth - userMessageCount);

  const showProcessingIndicator = sending || isSelectedBranchRunning;

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!canSendMore) return;
        if (isSelectedBranchRunning || sending) return;
        handleSend();
      }
    },
    [canSendMore, handleSend, isSelectedBranchRunning, sending]
  );

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!w-[80vw] !max-w-[80vw] h-[85vh] flex flex-col p-0">
        <DialogHeader className="px-6 py-4 border-b shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                <Sparkles className="h-5 w-5 text-primary" />
              </div>
              <div>
                <DialogTitle className="text-lg">Text verfeinern (Gekürzter Text)</DialogTitle>
                <p className="text-sm text-muted-foreground">Text verfeinern und anpassen</p>
              </div>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="space-y-4">

            {initLoading && versions.length === 0 && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Initialisiere Refinement.
              </div>
            )}

            {path.length === 0 && !initLoading && (
              <div className="text-sm text-muted-foreground">
                Noch keine Refinement-Daten gefunden. Sobald du eine Nachricht sendest, erscheint hier der Verlauf.
              </div>
            )}

            {/*
              const isRoot = v.id === "root";
              const isActive = v.id === activeVersionId;
              const assistantText = (v.assistantText || "").trim();

              const children = tree.childrenByParentId.get(v.id) ?? [];
              const selectedChildId = selectedChildByParentId[v.id];
              let selectedIndex = -1;
              if (children.length > 0) {
                selectedIndex = selectedChildId ? children.findIndex((c) => c.id === selectedChildId) : -1;
                if (selectedIndex === -1) selectedIndex = children.length - 1;
              }
              const showBranchNav = children.length > 1;

              return (
                <div key={v.id} className="space-y-3">
                  {isRoot ? (
                    <div className="flex justify-start">
                      <Card className="max-w-[85%] p-4 bg-muted/30 border-border">
                        <div className="flex items-center justify-between gap-3 mb-2">
                          <div className="text-xs text-muted-foreground">ASSISTANT \u00b7 Ausgangstext</div>
                          <div className="flex items-center gap-2">
                            {isActive && (
                              <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                                Aktiv
                              </span>
                            )}
                            {showBranchNav && (
                              <div className="flex items-center gap-1">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => handleCycleBranch(v.id, -1)}
                                  aria-label="Vorheriger Branch"
                                >
                                  <ChevronLeft className="h-4 w-4" />
                                </Button>
                                <span className="text-[11px] text-muted-foreground">
                                  Branch {selectedIndex + 1}/{children.length}
                                </span>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => handleCycleBranch(v.id, 1)}
                                  aria-label="N\u00e4chster Branch"
                                >
                                  <ChevronRight className="h-4 w-4" />
                                </Button>
                              </div>
                            )}
                            <Button size="sm" variant="ghost" onClick={() => handleCopy(assistantText)} disabled={!assistantText}>
                              <Copy className="h-4 w-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                onOpenTextViewer({
                                  title: `${kapitelLabel} - Refinement (Root)`,
                                  text: assistantText,
                                })
                              }
                              disabled={!assistantText}
                            >
                              Volltext
                            </Button>
                            <Button size="sm" variant="default" onClick={() => handleUseVersion(v)} disabled={isActive || !assistantText}>
                              <CheckCircle2 className="h-4 w-4 mr-2" />
                              \u00dcbernehmen
                            </Button>
                          </div>
                        </div>

                        <div className={cn("text-sm whitespace-pre-wrap leading-relaxed", "line-clamp-[12]")}>{assistantText}</div>
                      </Card>
                    </div>
                  ) : (
                    <>
                      <div className="flex justify-end">
                        <Card className="max-w-[85%] p-4 bg-primary text-primary-foreground border-primary/20">
                          <div className="flex items-center justify-between gap-3 mb-2">
                            <div className="text-xs text-primary-foreground/70">USER \u00b7 Iteration {v.depth}</div>
                            <div className="flex items-center gap-2">
                              {showBranchNav && (
                                <div className="flex items-center gap-1">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleCycleBranch(v.id, -1)}
                                    aria-label="Vorheriger Branch"
                                  >
                                    <ChevronLeft className="h-4 w-4" />
                                  </Button>
                                  <span className="text-[11px] text-primary-foreground/70">
                                    Branch {selectedIndex + 1}/{children.length}
                                  </span>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleCycleBranch(v.id, 1)}
                                    aria-label="Naechster Branch"
                                  >
                                    <ChevronRight className="h-4 w-4" />
                                  </Button>
                                </div>
                              )}
                              <Button size="sm" variant="ghost" onClick={() => handleCopy(v.userMessage || "")} disabled={!v.userMessage}>
                                <Copy className="h-4 w-4" />
                              </Button>
                              <Button size="sm" variant="secondary" onClick={() => startEdit(v)} disabled={!v.userMessage}>
                                <Pencil className="h-4 w-4 mr-1" />
                                Edit
                              </Button>
                            </div>
                          </div>

                          {editingVersionId === v.id ? (
                            <div className="space-y-3">
                              <div className="text-xs text-primary-foreground/70">
                                Bearbeiten: Erstellt einen neuen Branch (alte Version bleibt erhalten).
                              </div>
                              <Textarea
                                value={editMessage}
                                onChange={(e) => setEditMessage(e.target.value)}
                                className="min-h-[80px] max-h-[220px] overflow-y-auto resize-none bg-primary-foreground/10 text-primary-foreground placeholder:text-primary-foreground/70 border-primary-foreground/20 focus-visible:ring-primary-foreground/20"
                                disabled={editSending}
                              />
                              <div className="flex items-center gap-2 justify-end">
                                <Button size="sm" variant="ghost" onClick={cancelEdit} disabled={editSending}>
                                  <X className="h-4 w-4 mr-1" />
                                  Abbrechen
                                </Button>
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  onClick={() => submitEdit(v)}
                                  disabled={editSending || editMessage.trim().length === 0}
                                >
                                  {editSending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Check className="h-4 w-4 mr-1" />}
                                  Speichern
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="text-sm whitespace-pre-wrap leading-relaxed">{v.userMessage}</div>
                          )}
                        </Card>
                      </div>

                      <div className="flex justify-start">
                        <Card className="max-w-[85%] p-4 bg-card border-border">
                          <div className="flex items-center justify-between gap-3 mb-2">
                            <div className="text-xs text-muted-foreground">
                              ASSISTANT
                              {v.status === "running" && " \u00b7 l\u00e4uft."}
                              {v.status === "error" && " \u00b7 Fehler"}
                            </div>
                            <div className="flex items-center gap-2">
                              {isActive && (
                                <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                                  Aktiv
                                </span>
                              )}
                              {showBranchNav && (
                                <div className="flex items-center gap-1">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleCycleBranch(v.id, -1)}
                                    aria-label="Vorheriger Branch"
                                  >
                                    <ChevronLeft className="h-4 w-4" />
                                  </Button>
                                  <span className="text-[11px] text-muted-foreground">
                                    Branch {selectedIndex + 1}/{children.length}
                                  </span>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleCycleBranch(v.id, 1)}
                                    aria-label="Naechster Branch"
                                  >
                                    <ChevronRight className="h-4 w-4" />
                                  </Button>
                                </div>
                              )}
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleCopy(assistantText)}
                                disabled={!assistantText || v.status !== "success"}
                              >
                                <Copy className="h-4 w-4" />
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() =>
                                  onOpenTextViewer({
                                    title: `${kapitelLabel} - Refinement (Iteration ${v.depth})`,
                                    text: assistantText,
                                  })
                                }
                                disabled={!assistantText || v.status !== "success"}
                              >
                                Volltext
                              </Button>
                              <Button
                                size="sm"
                                variant="default"
                                onClick={() => handleUseVersion(v)}
                                disabled={v.status !== "success" || isActive || !assistantText}
                              >
                                <CheckCircle2 className="h-4 w-4 mr-2" />
                                \u00dcbernehmen
                              </Button>
                            </div>
                          </div>

                          {v.status === "running" ? (
                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              Antwort wird generiert.
                            </div>
                          ) : v.status === "error" ? (
                            <div className="text-sm text-destructive whitespace-pre-wrap">{AI_GENERIC_ERROR_MESSAGE}</div>
                          ) : (
                            <div className={cn("text-sm whitespace-pre-wrap leading-relaxed", "line-clamp-[12]")}>{assistantText}</div>
                          )}
                        </Card>
                      </div>
                    </>
                  )}
                </div>
              );
            })}

            */}

            <Card
              className={cn(
                "mb-6 border-2 transition-all !py-0 !gap-0",
                isOriginalActive
                  ? "bg-primary/5 border-primary"
                  : "bg-muted/30 border-dashed border-muted-foreground/30 hover:border-muted-foreground/50"
              )}
            >
              <div className="px-4 py-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium text-muted-foreground">Originaltext</span>
                    {isOriginalActive && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary text-primary-foreground text-xs font-medium">
                        <Star className="h-3 w-3 fill-current" />
                        Aktiv
                      </span>
                    )}
                  </div>
                </div>
                <p className="text-sm text-foreground/80 line-clamp-4 leading-relaxed">{originalText}</p>
              </div>
              <div className="flex items-center gap-1 px-4 py-2 border-t border-muted bg-muted/20">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-muted-foreground hover:text-foreground"
                  onClick={() => handleCopy(originalText || "", "original")}
                  disabled={!originalText}
                >
                  {copiedId === "original" ? (
                    <Check className="h-3.5 w-3.5 text-primary mr-1" />
                  ) : (
                    <Copy className="h-3.5 w-3.5 mr-1" />
                  )}
                  Kopieren
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-muted-foreground hover:text-foreground"
                  onClick={() => setViewingFullText({ title: "Originaltext", text: originalText || "" })}
                  disabled={!originalText}
                >
                  <Expand className="h-3.5 w-3.5 mr-1" />
                  Vollständig anzeigen
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-muted-foreground hover:text-foreground"
                  onClick={() => tree.root && openManualEditor(tree.root, "Originaltext manuell bearbeiten", originalText || "")}
                  disabled={!originalText || !tree.root || manualSaving}
                >
                  <Edit2 className="h-3.5 w-3.5 mr-1" />
                  Manuell bearbeiten
                </Button>
                {!isOriginalActive && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-muted-foreground hover:text-foreground"
                    onClick={() => tree.root && handleUseVersion(tree.root)}
                  >
                    <Star className="h-3.5 w-3.5 mr-1" />
                    Als aktiv setzen
                  </Button>
                )}
              </div>
            </Card>

            {path.slice(1).map((v) => {
              const parentId = v.parentVersionId || "root";
              const siblings = tree.childrenByParentId.get(parentId) ?? [];
              let branchIndex = siblings.findIndex((c) => c.id === v.id);
              if (branchIndex === -1) branchIndex = Math.max(0, siblings.length - 1);
              const showBranchNav = siblings.length > 1;

              const isActiveMessage = activeVersionId === v.id && !isOriginalActive;
              const isManualRevision = v.source === "manual" || v.manualEdit;
              const userText = String(v.userMessage ?? "");
              const assistantText = String(v.assistantText ?? "").trim();
              const needsExpand = assistantText.length > PREVIEW_LENGTH;

              return (
                <div key={v.id} className="space-y-4">
                  {showBranchNav && (
                    <div className="flex items-center justify-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        onClick={() => handleCycleBranch(parentId, -1)}
                        disabled={branchIndex === 0}
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        {branchIndex + 1} / {siblings.length}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        onClick={() => handleCycleBranch(parentId, 1)}
                        disabled={branchIndex === siblings.length - 1}
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  )}

                  <div className="flex justify-end">
                    <div className="max-w-[80%]">
                      {editingVersionId === v.id ? (
                        <div className="space-y-3">
                          <div className="text-xs text-muted-foreground mb-1">Nachricht bearbeiten</div>
                          <Textarea
                            value={editMessage}
                            onChange={(e) => setEditMessage(e.target.value)}
                            className="min-h-[100px] bg-background text-foreground border-border focus:border-primary resize-none"
                            autoFocus
                            disabled={editSending}
                          />
                          <div className="text-xs text-muted-foreground">
                            Das Bearbeiten erstellt einen neuen Zweig ab diesem Punkt.
                          </div>
                          <div className="flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={cancelEdit}
                              className="h-8 bg-transparent"
                              disabled={editSending}
                            >
                              Abbrechen
                            </Button>
                            <Button
                              size="sm"
                              onClick={() => submitEdit(v)}
                              className="h-8"
                              disabled={editSending || editMessage.trim().length === 0}
                            >
                              <Check className="h-3.5 w-3.5 mr-1.5" />
                              Speichern & Senden
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="bg-primary text-primary-foreground rounded-2xl px-4 py-3">
                            <p className="text-sm leading-relaxed whitespace-pre-wrap">
                              {isManualRevision ? "Manuelle Bearbeitung" : userText}
                            </p>
                          </div>
                          <div className="flex justify-end mt-1.5">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 px-2 text-xs bg-transparent"
                              onClick={() => startEdit(v)}
                              disabled={editSending || isSelectedBranchRunning || sending}
                            >
                              <Edit2 className="h-3 w-3 mr-1" />
                              Bearbeiten
                            </Button>
                          </div>
                        </>
                      )}
                    </div>
                  </div>

                  {v.status !== "running" && (
                    <div className="flex justify-start">
                      <Card
                        className={cn(
                          "max-w-[85%] border-2 transition-all overflow-hidden !py-0 !gap-0",
                          isActiveMessage
                            ? "bg-primary/5 border-primary"
                            : "bg-background border-muted hover:border-muted-foreground/30"
                        )}
                      >
                        <div className="px-4 py-4">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-muted-foreground font-medium">Revision {v.depth}</span>
                            {isManualRevision && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-muted text-muted-foreground text-xs font-medium">
                                <Edit2 className="h-3 w-3" />
                                Manuell
                              </span>
                            )}
                            {isActiveMessage && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary text-primary-foreground text-xs font-medium">
                                <Star className="h-3 w-3 fill-current" />
                                Aktiv
                              </span>
                            )}
                          </div>
                          {v.status === "error" ? (
                            <p className="text-sm leading-relaxed whitespace-pre-wrap text-destructive">
                              {AI_GENERIC_ERROR_MESSAGE}
                            </p>
                          ) : (
                            <p className="text-sm leading-relaxed whitespace-pre-wrap">
                              {needsExpand ? `${assistantText.substring(0, PREVIEW_LENGTH)}...` : assistantText}
                            </p>
                          )}
                        </div>
                        <div className="flex items-center gap-1 px-4 py-2 border-t border-muted bg-muted/20">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-muted-foreground hover:text-foreground"
                            onClick={() => handleCopy(assistantText, v.id)}
                            disabled={v.status !== "success" || !assistantText}
                          >
                            {copiedId === v.id ? (
                              <Check className="h-3.5 w-3.5 text-primary mr-1" />
                            ) : (
                              <Copy className="h-3.5 w-3.5 mr-1" />
                            )}
                            Kopieren
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-muted-foreground hover:text-foreground"
                            onClick={() => setViewingFullText({ title: `Revision ${v.depth}`, text: assistantText })}
                            disabled={v.status !== "success" || !assistantText}
                          >
                            <Expand className="h-3.5 w-3.5 mr-1" />
                            Vollständig anzeigen
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-muted-foreground hover:text-foreground"
                            onClick={() => openManualEditor(v, `Revision ${v.depth} manuell bearbeiten`, assistantText)}
                            disabled={v.status !== "success" || !assistantText || manualSaving}
                          >
                            <Edit2 className="h-3.5 w-3.5 mr-1" />
                            Manuell bearbeiten
                          </Button>
                          {!isActiveMessage && v.status === "success" && !!assistantText && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-muted-foreground hover:text-foreground"
                              onClick={() => handleUseVersion(v)}
                            >
                              <Star className="h-3.5 w-3.5 mr-1" />
                              Als aktiv setzen
                            </Button>
                          )}
                        </div>
                      </Card>
                    </div>
                  )}
                </div>
              );
            })}

            {showProcessingIndicator && (
              <div className="flex justify-start">
                <Card className="bg-background border-muted !py-0 !gap-0">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground p-4">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Text wird generiert...
                  </div>
                </Card>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="px-6 py-4 border-t bg-background shrink-0">
          {!canSendMore ? (
            <div className="text-center py-3">
              <p className="text-sm text-muted-foreground">
                Maximale Anzahl an Verfeinerungen ({maxDepth}) für diesen Pfad erreicht.
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Bearbeite eine vorherige Nachricht, um einen neuen Pfad zu starten.
              </p>
            </div>
          ) : (
            <div className="flex items-stretch gap-3">
              <div className="flex-1 relative">
                <Textarea
                  ref={textareaRef}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Beschreibe, wie der Text angepasst werden soll..."
                  className="h-[88px] resize-none pr-12"
                  disabled={sending || initLoading || isSelectedBranchRunning}
                />
                <div className="absolute bottom-2 right-2 text-xs text-muted-foreground">
                  {roundsRemaining} {roundsRemaining === 1 ? "Runde" : "Runden"} übrig
                </div>
              </div>
              <div className="flex flex-col justify-end">
                <Button
                  onClick={handleSend}
                  disabled={!message.trim() || sending || initLoading || isSelectedBranchRunning || isDepthLimitReached}
                  className="h-10 px-6"
                >
                  <Send className="h-4 w-4 mr-2" />
                  Senden
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
      </Dialog>

      {viewingFullText && (
        <Dialog open={true} onOpenChange={() => setViewingFullText(null)}>
          <DialogContent className="sm:max-w-4xl max-h-[90vh] flex flex-col" showCloseButton={false}>
            <DialogHeader className="flex-shrink-0 pr-0">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0 pr-2">
                  <DialogTitle className="text-xl leading-tight text-balance">{viewingFullText.title}</DialogTitle>
                  <div className="text-sm text-muted-foreground mt-1">
                    {viewingFullText.text.split(/\s+/).filter(Boolean).length.toLocaleString("de-DE")} Wörter
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button variant="outline" size="sm" onClick={() => handleCopy(viewingFullText.text, "fulltext")}>
                    {copiedId === "fulltext" ? (
                      <>
                        <CheckCircle2 className="h-4 w-4 mr-2 text-primary" />
                        Kopiert
                      </>
                    ) : (
                      <>
                        <Copy className="h-4 w-4 mr-2" />
                        Kopieren
                      </>
                    )}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setViewingFullText(null)} className="h-8 w-8 p-0">
                    <X className="h-4 w-4" />
                    <span className="sr-only">Schließen</span>
                  </Button>
                </div>
              </div>
            </DialogHeader>
            <div className="flex-1 overflow-y-auto mt-4 pr-2">
              <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap text-sm">{viewingFullText.text}</div>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {manualEditTarget && (
        <ManualRefinementEditorDialog
          open={true}
          title={manualEditTarget.title}
          initialText={manualEditTarget.text}
          saving={manualSaving}
          onOpenChange={(nextOpen) => {
            if (!nextOpen) setManualEditTarget(null);
          }}
          onSave={handleManualSave}
        />
      )}
    </>
  );
}
