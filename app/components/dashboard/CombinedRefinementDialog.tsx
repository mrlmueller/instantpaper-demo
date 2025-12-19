"use client";

import type React from "react";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ChevronLeft,
  ChevronRight,
  Send,
  Check,
  X,
  Sparkles,
  FileText,
  Copy,
  Loader2,
  Star,
  Expand,
  Zap,
  CheckCircle2,
  Edit2,
} from "lucide-react";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { firebaseApp } from "@/app/lib/firebase/config";
import { getFirestore, collection, doc, onSnapshot, updateDoc, serverTimestamp } from "firebase/firestore";
import { createCombinedRefinement, initCombinedRefinement } from "@/app/actions/kapitels";

type ModelChoice = "gpt-5-nano" | "gpt-5-mini" | "gpt-5.2";

type RefinementVersion = {
  id: string;
  parentVersionId: string | null;
  depth: number;
  userMessage?: string | null;
  assistantText?: string;
  status: "running" | "success" | "error";
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

const MODEL_PRICING_USD_PER_MILLION: Record<ModelChoice, { input: number; cached_input: number; output: number }> = {
  "gpt-5.2": { input: 1.75, cached_input: 0.175, output: 14.0 },
  "gpt-5-mini": { input: 0.25, cached_input: 0.025, output: 2.0 },
  "gpt-5-nano": { input: 0.05, cached_input: 0.005, output: 0.4 },
};

function isModelChoice(model: string): model is ModelChoice {
  return model === "gpt-5-nano" || model === "gpt-5-mini" || model === "gpt-5.2";
}

function estimateCostUsd(
  model: string,
  inputTokens: number,
  cachedInputTokens: number,
  outputTokens: number,
  reasoningTokens: number
) {
  if (!isModelChoice(model)) return null;
  const pricing = MODEL_PRICING_USD_PER_MILLION[model];
  const nonCached = Math.max(0, inputTokens - cachedInputTokens);
  const nonCachedCost = (nonCached / 1_000_000) * pricing.input;
  const cachedCost = (cachedInputTokens / 1_000_000) * pricing.cached_input;
  const outputCost = ((outputTokens + reasoningTokens) / 1_000_000) * pricing.output;
  return nonCachedCost + cachedCost + outputCost;
}

function formatEurFromUsd(usd: number) {
  const euros = usd;
  return `${euros.toFixed(2)} €`;
}

function toDate(value: unknown): Date {
  if (!value) return new Date(0);
  if (typeof value === "string") return new Date(value);
  if (typeof value === "object" && "toDate" in value && typeof (value as { toDate?: unknown }).toDate === "function") {
    return (value as { toDate: () => Date }).toDate();
  }
  return new Date(0);
}

interface CombinedRefinementDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kapitelId: string;
  runId: string;
  runModel: string;
  kapitelLabel: string;
  ensureOpenAIAccess: () => Promise<boolean>;
  onAuthFailure: () => void;
  onServerDown: (toastId?: string | number) => void;
  onOpenTextViewer: (content: { title: string; text: string }) => void;
}

export function CombinedRefinementDialog({
  open,
  onOpenChange,
  kapitelId,
  runId,
  runModel,
  kapitelLabel,
  ensureOpenAIAccess,
  onAuthFailure,
  onServerDown,
  onOpenTextViewer,
}: CombinedRefinementDialogProps) {
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

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const db = useMemo(() => getFirestore(firebaseApp), []);

  const combinedDocRef = useMemo(() => {
    if (!user?.uid) return null;
    return doc(db, "users", user.uid, "kapitels", kapitelId, "runs", runId, "artifacts", "combined");
  }, [db, user?.uid, kapitelId, runId]);

  const versionsRef = useMemo(() => {
    if (!combinedDocRef) return null;
    return collection(combinedDocRef, "versions");
  }, [combinedDocRef]);

  useEffect(() => {
    setSelectedChildByParentId({});
    setEditingVersionId(null);
    setEditMessage("");
    setMessage("");
  }, [kapitelId, runId]);

  useEffect(() => {
    if (open) return;
    setEditingVersionId(null);
    setEditMessage("");
    setEditSending(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (!kapitelId || !runId) return;
    if (!user?.uid) return;
    if (initLoading) return;

    setInitLoading(true);
    initCombinedRefinement(kapitelId, runId)
      .then((res) => {
        if (!res?.success) {
          const msg = (res?.error || "Initialisierung fehlgeschlagen.").toString();
          if (msg.toLowerCase().includes("sitzung")) {
            onAuthFailure();
            return;
          }
          if (msg.toLowerCase().includes("fastapi-server")) {
            onServerDown("refine-init-down");
            return;
          }
          toast.error("Refinement nicht verfügbar", { description: msg });
          return;
        }
        const data: any = res.data || {};
        setMaxDepth(Number(data.max_depth ?? 4));
        setActiveVersionId(String(data.active_version_id ?? "root"));
      })
      .finally(() => setInitLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kapitelId, runId, user?.uid]);

  useEffect(() => {
    if (!open) return;
    if (!combinedDocRef) return;

    const unsub = onSnapshot(
      combinedDocRef,
      (snap) => {
        const data: any = snap.data();
        if (!data) return;
        setActiveVersionId(String(data.refinement?.activeVersionId ?? "root"));
        setRefinementCostTotalUsd(Number(data.refinement?.costTotalUsd ?? 0));
      },
      (err) => {
        console.error("Combined refinement doc listen failed:", err);
      }
    );

    return () => unsub();
  }, [open, combinedDocRef]);

  useEffect(() => {
    if (!open) return;
    if (!versionsRef) return;

    const unsub = onSnapshot(
      versionsRef,
      (snap) => {
        const items: RefinementVersion[] = snap.docs.map((d) => {
          const data: any = d.data();
          return {
            id: d.id,
            parentVersionId: data.parentVersionId ?? null,
            depth: Number(data.depth ?? 0),
            userMessage: data.userMessage ?? null,
            assistantText: data.assistantText ?? "",
            status: data.status ?? "success",
            model: data.model ?? "",
            usage: data.usage ?? null,
            costUsd: typeof data.costUsd === "number" ? data.costUsd : Number(data.costUsd ?? 0),
            createdAt: data.createdAt,
            errorMessage: data.errorMessage ?? "",
          };
        });
        setVersions(items);
      },
      (err) => {
        console.error("Refinement versions listen failed:", err);
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

  const estimate = useMemo(() => {
    const usage = parentForNext?.usage;
    if (!usage) return null;
    const prevInput = Number(usage.inputTokens ?? 0);
    const prevOutputTotal = Number(usage.outputTokens ?? 0) + Number(usage.reasoningTokens ?? 0);

    // Heuristic requested by you:
    // input: previous input + previous output, output: previous output
    // TODO(text-refinement): incorporate cachedInputTokens into estimate carefully (range/upper bound).
    const estInput = prevInput + prevOutputTotal;
    const estOutput = prevOutputTotal;
    const estUsd = estimateCostUsd(runModel, estInput, 0, estOutput, 0);
    if (estUsd === null) return null;

    return {
      estUsd,
      estInput,
      estOutput,
    };
  }, [parentForNext?.usage, runModel]);

  useEffect(() => {
    if (!open) return;
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [open, path.length, parentForNext?.status, parentForNext?.id]);

  const handleUseVersion = useCallback(
    async (version: RefinementVersion) => {
      if (!combinedDocRef) return;
      if (!version.assistantText || version.status !== "success") return;

      try {
        await updateDoc(combinedDocRef, {
          content: version.assistantText,
          updatedAt: serverTimestamp(),
          "refinement.activeVersionId": version.id,
          "refinement.selectedAt": serverTimestamp(),
        });
        toast.success("Version übernommen", { description: "Der kombinierte Text wurde aktualisiert." });
      } catch (err: unknown) {
        console.error("Failed to set active refinement version:", err);
        toast.error("Konnte Version nicht übernehmen", {
          description: err instanceof Error ? err.message : "Unbekannter Fehler",
        });
      }
    },
    [combinedDocRef]
  );

  const handleSend = useCallback(async () => {
    if (!kapitelId || !runId) return;
    if (!user?.uid) return;
    const trimmed = message.trim();
    if (!trimmed) return;
    if (sending) return;

    if (!(await ensureOpenAIAccess())) return;

    if (nextDepth > maxDepth) {
      toast.error("Limit erreicht", {
        description: `Maximal ${maxDepth} Iterationen ab Root möglich. Bitte wähle eine andere Version oder starte neu.`,
      });
      return;
    }

    const parentVersionId = parentForNext?.id || "root";
    setSending(true);
    try {
      const res = await createCombinedRefinement(kapitelId, runId, parentVersionId, trimmed);
      if (!res?.success) {
        const msg = (res?.error || "Refinement konnte nicht gestartet werden.").toString();
        const lower = msg.toLowerCase();
        if (lower.includes("sitzung")) {
          onAuthFailure();
          return;
        }
        if (lower.includes("fastapi-server")) {
          onServerDown("refine-down");
          return;
        }
        toast.error("Refinement fehlgeschlagen", { description: msg });
        return;
      }

      const newVersionId = String((res as any)?.data?.version_id ?? "");
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
    kapitelId,
    runId,
    user?.uid,
    message,
    sending,
    maxDepth,
    nextDepth,
    parentForNext?.id,
    onAuthFailure,
    onServerDown,
  ]);

  const handleCycleBranch = useCallback(
    (parentId: string, delta: -1 | 1) => {
      const children = tree.childrenByParentId.get(parentId) ?? [];
      if (children.length < 2) return;

      setSelectedChildByParentId((prev) => {
        const currentId = prev[parentId];
        let index = currentId ? children.findIndex((c) => c.id === currentId) : -1;
        if (index === -1) index = children.length - 1;
        const nextIndex = index + delta;
        if (nextIndex < 0 || nextIndex >= children.length) return prev;
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

      const trimmed = editMessage.trim();
      if (!trimmed) return;
      if (editSending) return;

      if (!(await ensureOpenAIAccess())) return;

      const parentVersionId = version.parentVersionId || "root";
      const parentDepth = Number(tree.byId.get(parentVersionId)?.depth ?? 0);
      const newDepth = parentDepth + 1;
      if (newDepth > maxDepth) {
        toast.error("Limit erreicht", {
          description: `Maximal ${maxDepth} Iterationen ab Root m”glich.`,
        });
        return;
      }

      setEditSending(true);
      try {
        const res = await createCombinedRefinement(kapitelId, runId, parentVersionId, trimmed);
        if (!res?.success) {
          const msg = (res?.error || "Refinement konnte nicht gestartet werden.").toString();
          const lower = msg.toLowerCase();
          if (lower.includes("sitzung")) {
            onAuthFailure();
            return;
          }
          if (lower.includes("fastapi-server")) {
            onServerDown("refine-edit-down");
            return;
          }
          toast.error("Refinement fehlgeschlagen", { description: msg });
          return;
        }

        const newVersionId = String((res as any)?.data?.version_id ?? "");
        if (newVersionId) {
          setSelectedChildByParentId((prev) => ({ ...prev, [parentVersionId]: newVersionId }));
        }

        cancelEdit();
        toast.success("Branch erstellt", {
          description: `Iteration ${newDepth}/${maxDepth} wird berechnet...`,
        });
      } finally {
        setEditSending(false);
      }
    },
    [
      ensureOpenAIAccess,
      kapitelId,
      runId,
      user?.uid,
      editMessage,
      editSending,
      maxDepth,
      tree.byId,
      cancelEdit,
      onAuthFailure,
      onServerDown,
    ]
  );

  const handleCopy = useCallback(async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }, []);

  const formatCost = (cents: number) => `${(cents / 100).toFixed(2)} €`;
  const PREVIEW_LENGTH = 300;

  const originalText = (tree.root?.assistantText || "").toString();
  const isOriginalActive = activeVersionId === "root";

  const userMessageCount = Math.max(0, path.length - 1);
  const canSendMore = userMessageCount < maxDepth;
  const roundsRemaining = Math.max(0, maxDepth - userMessageCount);

  const estimatedCostCents = estimate ? Math.round(estimate.estUsd * 100) : 0;
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
                <DialogTitle className="text-lg">Kombinierten Text verfeinern</DialogTitle>
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
                  Initialisiere Refinement…
                </div>
              )}

              {path.length === 0 && !initLoading && (
                <div className="text-sm text-muted-foreground">
                  Noch keine Refinement-Daten gefunden. Sobald du eine Nachricht sendest, erscheint hier der Verlauf.
                </div>
              )}

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
                              <p className="text-sm leading-relaxed whitespace-pre-wrap">{userText}</p>
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
                              {isActiveMessage && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary text-primary-foreground text-xs font-medium">
                                  <Star className="h-3 w-3 fill-current" />
                                  Aktiv
                                </span>
                              )}
                            </div>
                            {v.status === "error" ? (
                              <p className="text-sm leading-relaxed whitespace-pre-wrap text-destructive">
                                {v.errorMessage || "Unbekannter Fehler"}
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
              <div className="flex flex-col gap-2 justify-between">
                <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-muted/40 h-10">
                  <div className="flex items-center gap-1.5">
                    <Zap className="h-4 w-4 text-amber-500" />
                    <span className="text-sm font-medium">{formatCost(estimatedCostCents)}</span>
                  </div>
                  <div className="h-4 w-px bg-border" />
                  <span className="text-xs text-muted-foreground">ca. Kosten</span>
                </div>
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
          <DialogContent className="sm:max-w-4xl max-h-[90vh] flex flex-col [&>button]:hidden">
            <DialogHeader className="flex-shrink-0 pr-0">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0 pr-2">
                  <DialogTitle className="text-xl leading-tight text-balance">{viewingFullText.title}</DialogTitle>
                  <div className="text-sm text-muted-foreground mt-1">
                    {viewingFullText.text.split(/\\s+/).filter(Boolean).length.toLocaleString("de-DE")} Wörter
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
    </>
  );
}
