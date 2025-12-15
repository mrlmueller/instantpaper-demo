"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { MessageSquareText, Send, CheckCircle2, Loader2, Copy } from "lucide-react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { firebaseApp } from "@/app/lib/firebase/config";
import { getFirestore, collection, doc, onSnapshot, updateDoc, serverTimestamp } from "firebase/firestore";
import { createCombinedRefinement, initCombinedRefinement } from "@/app/actions/kapitels";

type ModelChoice = "gpt-5-nano" | "gpt-5-mini" | "gpt-5.2";

type RefinementVersion = {
  id: string;
  parent_version_id: string | null;
  depth: number;
  user_message?: string | null;
  assistant_text?: string;
  status: "running" | "success" | "error";
  model?: string;
  usage?: {
    input_tokens: number;
    cached_input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    total_tokens: number;
  } | null;
  cost?: number; // USD float
  created_at?: any;
  error_message?: string;
};

const MODEL_PRICING_USD_PER_MILLION: Record<ModelChoice, { input: number; cached_input: number; output: number }> = {
  "gpt-5.2": { input: 1.75, cached_input: 0.175, output: 14.0 },
  "gpt-5-mini": { input: 0.25, cached_input: 0.025, output: 2.0 },
  "gpt-5-nano": { input: 0.05, cached_input: 0.005, output: 0.4 },
};

function estimateCostUsd(
  model: ModelChoice,
  inputTokens: number,
  cachedInputTokens: number,
  outputTokens: number,
  reasoningTokens: number
) {
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

function toDate(value: any): Date {
  if (!value) return new Date(0);
  if (typeof value === "string") return new Date(value);
  if (value?.toDate) return value.toDate();
  return new Date(0);
}

interface CombinedRefinementDialogProps {
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

export function CombinedRefinementDialog({
  open,
  onOpenChange,
  kapitelId,
  runId,
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
  const [model, setModel] = useState<ModelChoice>("gpt-5-mini");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);

  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const db = useMemo(() => getFirestore(firebaseApp), []);

  const combinedDocRef = useMemo(() => {
    if (!user?.uid) return null;
    return doc(db, "users", user.uid, "kapitels", kapitelId, "runs", runId, "combined", "combined");
  }, [db, user?.uid, kapitelId, runId]);

  const versionsRef = useMemo(() => {
    if (!combinedDocRef) return null;
    return collection(combinedDocRef, "versions");
  }, [combinedDocRef]);

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
        setActiveVersionId(String(data.refinement_active_version_id ?? "root"));
        setRefinementCostTotalUsd(Number(data.refinement_cost_total ?? 0));
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
            parent_version_id: data.parent_version_id ?? null,
            depth: Number(data.depth ?? 0),
            user_message: data.user_message ?? null,
            assistant_text: data.assistant_text ?? "",
            status: data.status ?? "success",
            model: data.model ?? "",
            usage: data.usage ?? null,
            cost: typeof data.cost === "number" ? data.cost : Number(data.cost ?? 0),
            created_at: data.created_at,
            error_message: data.error_message ?? "",
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

  const headVersion = useMemo(() => {
    if (versions.length === 0) return null;
    return versions.reduce<RefinementVersion | null>((best, current) => {
      if (!best) return current;
      const bestDepth = best.depth ?? 0;
      const currentDepth = current.depth ?? 0;
      if (currentDepth !== bestDepth) return currentDepth > bestDepth ? current : best;
      return toDate(current.created_at) > toDate(best.created_at) ? current : best;
    }, null);
  }, [versions]);

  const path = useMemo(() => {
    if (!headVersion) return [];
    const byId = new Map(versions.map((v) => [v.id, v]));
    const chain: RefinementVersion[] = [];
    let current: RefinementVersion | undefined = headVersion;
    let guard = 0;
    while (current && guard < 32) {
      guard++;
      chain.push(current);
      current = current.parent_version_id ? byId.get(current.parent_version_id) : undefined;
    }
    return chain.reverse();
  }, [headVersion, versions]);

  const parentForNext = headVersion ?? versions.find((v) => v.id === "root") ?? null;
  const nextDepth = (parentForNext?.depth ?? 0) + 1;

  const estimate = useMemo(() => {
    const usage = parentForNext?.usage;
    if (!usage) return null;
    const prevInput = Number(usage.input_tokens ?? 0);
    const prevOutputTotal = Number(usage.output_tokens ?? 0) + Number(usage.reasoning_tokens ?? 0);

    // Heuristic requested by you:
    // input: previous input + previous output, output: previous output
    // TODO(text-refinement): incorporate cached_input_tokens into estimate carefully (range/upper bound).
    const estInput = prevInput + prevOutputTotal;
    const estOutput = prevOutputTotal;
    const estUsd = estimateCostUsd(model, estInput, 0, estOutput, 0);

    return {
      estUsd,
      estInput,
      estOutput,
    };
  }, [parentForNext?.usage, model]);

  useEffect(() => {
    if (!open) return;
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [open, path.length, headVersion?.status]);

  const handleUseVersion = useCallback(
    async (version: RefinementVersion) => {
      if (!combinedDocRef) return;
      if (!version.assistant_text || version.status !== "success") return;

      try {
        await updateDoc(combinedDocRef, {
          combined_content: version.assistant_text,
          refinement_active_version_id: version.id,
          refinement_selected_at: serverTimestamp(),
        });
        toast.success("Version übernommen", { description: "Der kombinierte Text wurde aktualisiert." });
      } catch (err: any) {
        console.error("Failed to set active refinement version:", err);
        toast.error("Konnte Version nicht übernehmen", {
          description: err?.message || "Unbekannter Fehler",
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
      const res = await createCombinedRefinement(kapitelId, runId, parentVersionId, trimmed, model);
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
    model,
    maxDepth,
    nextDepth,
    parentForNext?.id,
    onAuthFailure,
    onServerDown,
  ]);

  const handleCopy = useCallback(async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast.success("Kopiert");
  }, []);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-5xl max-h-[90vh] flex flex-col [&>button]:hidden">
        <DialogHeader className="flex-shrink-0">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <MessageSquareText className="h-4 w-4 text-primary" />
            </div>
            Text verfeinern (Kombinierter Text)
          </DialogTitle>
          <DialogDescription>
            Verfeinere den Text iterativ. Der Haupttext wird erst aktualisiert, wenn du eine Version übernimmst.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between gap-4 mt-2">
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{kapitelLabel}</span>
            <span className="mx-2">·</span>
            <span>Max. Tiefe: {maxDepth}</span>
            <span className="mx-2">·</span>
            <span>Aktiv: {activeVersionId}</span>
            <span className="mx-2">·</span>
            <span>Refinement-Kosten: {formatEurFromUsd(refinementCostTotalUsd)}</span>
          </div>

          <div className="flex items-center gap-3">
            <div className="min-w-[220px]">
              <Label className="text-xs text-muted-foreground">Modell</Label>
              <Select value={model} onValueChange={(v) => setModel(v as ModelChoice)}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gpt-5-nano">gpt-5-nano (günstig)</SelectItem>
                  <SelectItem value="gpt-5-mini">gpt-5-mini (empfohlen)</SelectItem>
                  <SelectItem value="gpt-5.2">gpt-5.2 (beste Qualität)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="text-right">
              <div className="text-xs text-muted-foreground">Schätzung (ohne Cache)</div>
              <div className="text-sm font-medium">
                {estimate ? `~ ${formatEurFromUsd(estimate.estUsd)}` : "—"}
              </div>
              {estimate && (
                <div className="text-[11px] text-muted-foreground">
                  In: ~{estimate.estInput.toLocaleString()} · Out: ~{estimate.estOutput.toLocaleString()}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-hidden mt-4 border rounded-lg">
          <ScrollArea className="h-full">
            <div className="p-4 space-y-4">
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

              {path.map((v) => {
                const isRoot = v.id === "root";
                const isActive = v.id === activeVersionId;
                const assistantText = (v.assistant_text || "").trim();

                return (
                  <div key={v.id} className="space-y-3">
                    {isRoot ? (
                      <div className="flex justify-start">
                        <Card className="max-w-[85%] p-4 bg-muted/30 border-border">
                          <div className="flex items-center justify-between gap-3 mb-2">
                            <div className="text-xs text-muted-foreground">
                              ASSISTANT <span className="mx-1">·</span> Ausgangstext
                            </div>
                            <div className="flex items-center gap-2">
                              {isActive && (
                                <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                                  Aktiv
                                </span>
                              )}
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleCopy(assistantText)}
                                disabled={!assistantText}
                              >
                                <Copy className="h-4 w-4" />
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() =>
                                  onOpenTextViewer({
                                    title: `${kapitelLabel} - Ausgangstext`,
                                    text: assistantText,
                                  })
                                }
                                disabled={!assistantText}
                              >
                                Volltext
                              </Button>
                              <Button
                                size="sm"
                                variant="default"
                                onClick={() => handleUseVersion(v)}
                                disabled={isActive || !assistantText}
                              >
                                <CheckCircle2 className="h-4 w-4 mr-2" />
                                Übernehmen
                              </Button>
                            </div>
                          </div>
                          <div className="text-sm whitespace-pre-wrap leading-relaxed line-clamp-[10]">{assistantText}</div>
                        </Card>
                      </div>
                    ) : (
                      <>
                        <div className="flex justify-end">
                          <Card className="max-w-[85%] p-4 bg-primary text-primary-foreground border-primary/20">
                            <div className="text-xs opacity-80 mb-2">USER · Iteration {v.depth}</div>
                            <div className="text-sm whitespace-pre-wrap leading-relaxed">{v.user_message}</div>
                          </Card>
                        </div>

                        <div className="flex justify-start">
                          <Card className="max-w-[85%] p-4 bg-card border-border">
                            <div className="flex items-center justify-between gap-3 mb-2">
                              <div className="text-xs text-muted-foreground">
                                ASSISTANT <span className="mx-1">·</span> {v.model || model}
                                {v.status === "running" && " · läuft…"}
                                {v.status === "error" && " · Fehler"}
                              </div>
                              <div className="flex items-center gap-2">
                                {isActive && (
                                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                                    Aktiv
                                  </span>
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
                                  Übernehmen
                                </Button>
                              </div>
                            </div>

                            {v.status === "running" ? (
                              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Antwort wird generiert…
                              </div>
                            ) : v.status === "error" ? (
                              <div className="text-sm text-destructive whitespace-pre-wrap">
                                {v.error_message || "Unbekannter Fehler"}
                              </div>
                            ) : (
                              <div className={cn("text-sm whitespace-pre-wrap leading-relaxed", "line-clamp-[12]")}>
                                {assistantText}
                              </div>
                            )}
                          </Card>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}

              <div ref={scrollAnchorRef} />
            </div>
          </ScrollArea>
        </div>

        <div className="pt-4 border-t mt-4 flex-shrink-0">
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <Label className="text-xs text-muted-foreground">Deine Anweisung</Label>
              <Textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder='z.B. "Schreibe das nochmal, aber ohne Wiederholungen und mit klareren Übergängen."'
                className="mt-1.5 min-h-[80px] resize-none"
                disabled={sending}
              />
              <div className="mt-1 text-[11px] text-muted-foreground">
                Nächste Iteration: {nextDepth}/{maxDepth}
              </div>
            </div>
            <Button
              onClick={handleSend}
              disabled={sending || initLoading || message.trim().length === 0 || nextDepth > maxDepth}
              className="h-10"
            >
              {sending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Send className="h-4 w-4 mr-2" />}
              Senden
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

