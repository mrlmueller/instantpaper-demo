"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  Loader2,
  Pencil,
  Plus,
  SendHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Checkbox } from "@/components/ui/checkbox";
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type {
  GliederungDraft,
  GliederungDraftOutput,
} from "@/app/types/gliederung";
import { cn } from "@/lib/utils";

type KapitelValidation = {
  duplicateIds: Set<string>;
  invalidIds: Set<string>;
  tooDeepIds: Set<string>;
  jumpWarnings: string[];
  missingParentWarnings: string[];
};

function formatGliederungModelLabel(model: string): string {
  const m = String(model || "").trim();
  if (!m) return "—";
  if (m === "gpt-5-nano") return "GPT-5 nano";
  if (m === "gpt-5-mini") return "GPT-5 mini";
  if (m === "gpt-5.4") return "GPT-5.4";
  if (m === "gpt-5.2") return "GPT-5.2";
  return m;
}

function isAllowedKapitelNummerInput(value: string): boolean {
  const v = String(value || "").trim();
  if (v === "") return true;
  if (!/^[0-9.]+$/.test(v)) return false;
  if (v.startsWith(".")) return false;
  if (v.includes("..")) return false;

  const endsWithDot = v.endsWith(".");
  const segs = v.split(".");
  if (endsWithDot) segs.pop();
  if (segs.length === 0) return false;
  if (segs.length > 3) return false;
  if (endsWithDot && segs.length >= 3) return false;

  return segs.every((s) => /^[1-9]\d*$/.test(s));
}

function validateKapitel(
  output: GliederungDraftOutput | null | undefined,
): KapitelValidation {
  const chapters = output?.kapitel ?? [];
  const counts = new Map<string, number>();
  const nummerById = new Map<string, string>();
  const duplicateIds = new Set<string>();
  const invalidIds = new Set<string>();
  const tooDeepIds = new Set<string>();

  for (const ch of chapters) {
    const nummer = String(ch?.nummer ?? "").trim();
    nummerById.set(ch.id, nummer);
    if (!nummer) {
      invalidIds.add(ch.id);
      continue;
    }
    counts.set(nummer, (counts.get(nummer) ?? 0) + 1);

    const parts = nummer.split(".");
    if (parts.length > 3) {
      tooDeepIds.add(ch.id);
      invalidIds.add(ch.id);
      continue;
    }
    const ok = parts.every((p) => /^[1-9]\d*$/.test(p));
    if (!ok) invalidIds.add(ch.id);
  }

  for (const [nummer, count] of counts.entries()) {
    if (count <= 1) continue;
    for (const [id, n] of nummerById.entries()) {
      if (n === nummer) duplicateIds.add(id);
    }
  }

  const valid = chapters
    .map((ch) => {
      const nummer = String(ch?.nummer ?? "").trim();
      const parts = nummer ? nummer.split(".") : [];
      const ok =
        parts.length > 0 &&
        parts.length <= 3 &&
        parts.every((p) => /^[1-9]\d*$/.test(p));
      return ok
        ? {
            id: ch.id,
            nummer,
            parts: parts.map((p) => Number(p)),
          }
        : null;
    })
    .filter(Boolean) as Array<{ id: string; nummer: string; parts: number[] }>;

  const existing = new Set(valid.map((v) => v.nummer));
  const missingParentWarnings: string[] = [];
  for (const v of valid) {
    if (v.parts.length <= 1) continue;
    const parent = v.parts.slice(0, -1).join(".");
    if (!existing.has(parent)) missingParentWarnings.push(v.nummer);
  }

  const groups = new Map<string, number[]>();
  for (const v of valid) {
    const prefix = v.parts.slice(0, -1).join(".");
    const last = v.parts[v.parts.length - 1];
    const list = groups.get(prefix) ?? [];
    list.push(last);
    groups.set(prefix, list);
  }

  const jumpWarnings: string[] = [];
  for (const [prefix, nums] of groups.entries()) {
    const uniq = Array.from(new Set(nums)).sort((a, b) => a - b);
    if (uniq.length <= 1) continue;
    let hasJump = false;
    for (let i = 0; i < uniq.length; i++) {
      const expected = i === 0 ? 1 : uniq[i - 1] + 1;
      if (uniq[i] !== expected) {
        hasJump = true;
        break;
      }
    }
    if (hasJump) jumpWarnings.push(prefix || "Hauptkapitel");
  }

  return {
    duplicateIds,
    invalidIds,
    tooDeepIds,
    jumpWarnings,
    missingParentWarnings,
  };
}

interface GliederungWorkspaceProps {
  drafts: GliederungDraft[];
  selectedDraftId: string | null;
  onSelectDraft: (id: string) => void;
  onOpenCreate: () => void;
  onOpenManualKapitel?: () => void;
  onUpdateDraftOutput: (
    draftId: string,
    output: GliederungDraftOutput,
  ) => Promise<void>;
  onRefineDraft: (draftId: string, message: string) => Promise<void>;
  onApplyDraft: (
    draftId: string,
    output: GliederungDraftOutput,
  ) => Promise<void>;
  isApplying: boolean;
  isRefining: boolean;
}

export function GliederungWorkspace({
  drafts,
  selectedDraftId,
  onSelectDraft,
  onOpenCreate,
  onOpenManualKapitel,
  onUpdateDraftOutput,
  onRefineDraft,
  onApplyDraft,
  isApplying,
  isRefining,
}: GliederungWorkspaceProps) {
  const activeDrafts = useMemo(() => {
    return drafts
      .filter((d) => !d.archived)
      .slice()
      .sort(
        (a, b) =>
          (b.updatedAt?.valueOf?.() || 0) - (a.updatedAt?.valueOf?.() || 0),
      );
  }, [drafts]);

  const selectedDraft = useMemo(() => {
    if (!selectedDraftId) return null;
    return drafts.find((d) => d.id === selectedDraftId) ?? null;
  }, [drafts, selectedDraftId]);

  type DraftGroup = {
    rootId: string;
    drafts: GliederungDraft[];
    createdAt: Date;
  };
  const draftGroups: DraftGroup[] = useMemo(() => {
    const byRoot = new Map<string, GliederungDraft[]>();
    for (const d of activeDrafts) {
      const rootId = String(
        (d as any).rootId || (d as any).rootDraftId || d.id,
      );
      const list = byRoot.get(rootId) ?? [];
      list.push(d);
      byRoot.set(rootId, list);
    }

    const versionOf = (d: GliederungDraft) => Number((d as any).version ?? 1);
    const groups: DraftGroup[] = Array.from(byRoot.entries()).map(
      ([rootId, list]) => {
        const sorted = list
          .slice()
          .sort(
            (a, b) =>
              versionOf(a) - versionOf(b) ||
              (a.createdAt?.valueOf?.() || 0) - (b.createdAt?.valueOf?.() || 0),
          );
        return {
          rootId,
          drafts: sorted,
          createdAt: sorted[0]?.createdAt ?? new Date(0),
        };
      },
    );

    groups.sort(
      (a, b) =>
        (a.createdAt?.valueOf?.() || 0) - (b.createdAt?.valueOf?.() || 0),
    );
    return groups;
  }, [activeDrafts]);

  useEffect(() => {
    if (selectedDraftId) return;
    if (activeDrafts.length === 0) return;
    onSelectDraft(activeDrafts[0].id);
  }, [activeDrafts, onSelectDraft, selectedDraftId]);

  const selectedDraftSafe = selectedDraft ?? activeDrafts[0] ?? null;

  const [deleteKapitelId, setDeleteKapitelId] = useState<string | null>(null);

  const [output, setOutput] = useState<GliederungDraftOutput | null>(
    selectedDraftSafe?.output ?? null,
  );
  const [version, setVersion] = useState(0);
  const savedVersionRef = useRef(0);
  const attemptedVersionRef = useRef(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [refineMessage, setRefineMessage] = useState("");
  const [localRefining, setLocalRefining] = useState(false);

  const [openKapitelIds, setOpenKapitelIds] = useState<string[]>([]);
  const [editingKapitelId, setEditingKapitelId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{
    nummer: string;
    titel: string;
    beschreibung: string;
  }>({
    nummer: "",
    titel: "",
    beschreibung: "",
  });

  const isDirty = version !== savedVersionRef.current;

  useEffect(() => {
    setOutput(null);
    setVersion(0);
    savedVersionRef.current = 0;
    attemptedVersionRef.current = 0;
    setSaving(false);
    setSaveError(null);
    setRefineMessage("");
    setLocalRefining(false);
    setOpenKapitelIds([]);
    setEditingKapitelId(null);
    setEditForm({ nummer: "", titel: "", beschreibung: "" });
  }, [selectedDraftSafe?.id]);

  useEffect(() => {
    if (!selectedDraftSafe?.output) return;
    if (isDirty) return;
    setOutput(selectedDraftSafe.output);
  }, [isDirty, selectedDraftSafe?.output]);

  const validation = useMemo(() => validateKapitel(output), [output]);

  const chapters = output?.kapitel ?? [];
  const total = chapters.length;
  const reviewedCount = chapters.filter((c) => c.reviewed).length;
  const reviewProgress =
    total > 0 ? Math.round((reviewedCount / total) * 100) : 0;

  const hasStructuralBlockingErrors =
    validation.invalidIds.size > 0 || validation.tooDeepIds.size > 0;
  const hasDuplicateWarnings = validation.duplicateIds.size > 0;
  const hasBlockingErrors = hasStructuralBlockingErrors;
  const allReviewed = total > 0 && reviewedCount === total;
  const remainingToReview = Math.max(0, total - reviewedCount);

  const sortedChapters = useMemo(() => {
    const parse = (nummer: string): number[] | null => {
      const n = String(nummer || "").trim();
      if (!n) return null;
      const parts = n.split(".");
      if (parts.length === 0 || parts.length > 3) return null;
      if (!parts.every((p) => /^[1-9]\d*$/.test(p))) return null;
      return parts.map((p) => Number(p));
    };

    const cmp = (a: number[], b: number[]) => {
      for (let i = 0; i < Math.max(a.length, b.length); i++) {
        const na = a[i] ?? 0;
        const nb = b[i] ?? 0;
        if (na !== nb) return na - nb;
      }
      return 0;
    };

    return chapters.slice().sort((a, b) => {
      const pa = parse(a.nummer);
      const pb = parse(b.nummer);
      if (pa && pb) return cmp(pa, pb);
      if (pa) return -1;
      if (pb) return 1;
      return String(a.id).localeCompare(String(b.id));
    });
  }, [chapters]);

  const bumpVersion = () => setVersion((v) => v + 1);

  const updateKapitel = (
    id: string,
    patch: Partial<GliederungDraftOutput["kapitel"][number]>,
  ) => {
    setOutput((prev) => {
      if (!prev) return prev;
      const touchesContent =
        "nummer" in patch || "titel" in patch || "beschreibung" in patch;
      return {
        ...prev,
        kapitel: prev.kapitel.map((ch) => {
          if (ch.id !== id) return ch;
          const next = { ...ch, ...patch };
          if (touchesContent) next.reviewed = false;
          return next;
        }),
      };
    });
    bumpVersion();
  };

  const deleteKapitel = (id: string) => {
    setOutput((prev) => {
      if (!prev) return prev;
      return { ...prev, kapitel: prev.kapitel.filter((ch) => ch.id !== id) };
    });
    bumpVersion();
  };

  const makeKapitelId = () => {
    try {
      return crypto.randomUUID();
    } catch {
      return `kapitel_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    }
  };

  const isKapitelOpen = (id: string) =>
    openKapitelIds.includes(id) || editingKapitelId === id;

  const toggleKapitelOpen = (id: string) => {
    if (editingKapitelId === id) return;
    setOpenKapitelIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const startEditKapitel = (
    kapitel: GliederungDraftOutput["kapitel"][number],
  ) => {
    setEditingKapitelId(kapitel.id);
    setEditForm({
      nummer: String(kapitel.nummer ?? ""),
      titel: String(kapitel.titel ?? ""),
      beschreibung: String(kapitel.beschreibung ?? ""),
    });
    setOpenKapitelIds((prev) =>
      prev.includes(kapitel.id) ? prev : [...prev, kapitel.id],
    );
  };

  const cancelEditKapitel = () => {
    setEditingKapitelId(null);
  };

  const saveEditKapitel = () => {
    if (!editingKapitelId) return;
    const cleanedNummer = editForm.nummer.replace(/\.$/, "").trim();
    updateKapitel(editingKapitelId, {
      nummer: cleanedNummer,
      titel: editForm.titel,
      beschreibung: editForm.beschreibung,
      reviewed: false,
    });
    setEditingKapitelId(null);
  };

  const addKapitelManually = () => {
    if (!output) return;

    const firstLevelNums = output.kapitel
      .map(
        (c) =>
          String(c.nummer || "")
            .trim()
            .split(".")[0],
      )
      .filter((p) => /^[1-9]\d*$/.test(p))
      .map((p) => Number(p));

    const nextNum = String(Math.max(0, ...firstLevelNums) + 1);
    const id = makeKapitelId();

    const newKapitel: GliederungDraftOutput["kapitel"][number] = {
      id,
      reviewed: false,
      nummer: nextNum,
      titel: "",
      beschreibung: "",
      seitenumfang: "",
      relevanteStudienbriefKapitel: [],
      externeQuellenErforderlich: false,
    };

    setOutput((prev) => {
      if (!prev) return prev;
      return { ...prev, kapitel: [...prev.kapitel, newKapitel] };
    });
    bumpVersion();
    startEditKapitel(newKapitel);
  };

  useEffect(() => {
    if (!selectedDraftSafe || !output) return;
    if (version === savedVersionRef.current) return;
    if (saving) return;
    if (version === attemptedVersionRef.current) return;

    const t = setTimeout(async () => {
      if (!selectedDraftSafe || !output) return;
      const versionToSave = version;
      attemptedVersionRef.current = versionToSave;
      setSaving(true);
      try {
        await onUpdateDraftOutput(selectedDraftSafe.id, output);
        savedVersionRef.current = versionToSave;
        setSaveError(null);
      } catch (err: unknown) {
        setSaveError(
          err instanceof Error ? err.message : "Speichern fehlgeschlagen.",
        );
      } finally {
        setSaving(false);
      }
    }, 800);

    return () => clearTimeout(t);
  }, [onUpdateDraftOutput, output, saving, selectedDraftSafe, version]);

  const handleSaveNow = async () => {
    if (!selectedDraftSafe || !output || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await onUpdateDraftOutput(selectedDraftSafe.id, output);
      savedVersionRef.current = version;
      attemptedVersionRef.current = version;
    } catch (err: unknown) {
      setSaveError(
        err instanceof Error ? err.message : "Speichern fehlgeschlagen.",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleApply = async () => {
    if (!selectedDraftSafe || !output) return;
    if (isApplying || saving || isRefining || localRefining) return;
    if (!allReviewed || hasBlockingErrors) return;
    if (isDirty) {
      await handleSaveNow();
      if (version !== savedVersionRef.current) return;
    }
    await onApplyDraft(selectedDraftSafe.id, output);
  };

  const handleRefine = async () => {
    if (!selectedDraftSafe || !output) return;
    const msg = refineMessage.trim();
    if (!msg) return;
    if (localRefining || isRefining) return;
    if (isApplying || saving) return;

    if (isDirty) {
      await handleSaveNow();
      if (version !== savedVersionRef.current) return;
    }

    setLocalRefining(true);
    try {
      await onRefineDraft(selectedDraftSafe.id, msg);
      setRefineMessage("");
    } finally {
      setLocalRefining(false);
    }
  };

  if (activeDrafts.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center px-6">
          <div className="mx-auto h-12 w-12 rounded-full bg-muted flex items-center justify-center">
            <FileText className="h-5 w-5 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-foreground">
            Projekt starten
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Erstelle eine Gliederung für deine Arbeit.
          </p>

          <div className="mt-5 flex flex-col items-center gap-3">
            <Button onClick={onOpenCreate} className="w-[220px]">
              <Sparkles className="h-4 w-4 mr-2" />
              Mit KI generieren
            </Button>
            <button
              type="button"
              onClick={() => onOpenManualKapitel?.()}
              disabled={!onOpenManualKapitel}
              className={cn(
                "inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors",
                !onOpenManualKapitel ? "opacity-60 cursor-not-allowed" : "",
              )}
            >
              <Plus className="h-4 w-4" />
              Manuell erstellen
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!selectedDraftSafe) {
    return null;
  }

  const selectedVersionNumber = Number((selectedDraftSafe as any).version ?? 1);
  const modelLabel = selectedDraftSafe.model
    ? formatGliederungModelLabel(selectedDraftSafe.model)
    : "—";

  const hasAnyNotices =
    hasStructuralBlockingErrors ||
    hasDuplicateWarnings ||
    validation.jumpWarnings.length > 0 ||
    validation.missingParentWarnings.length > 0;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-6 pt-6 pb-5 border-b">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xl font-semibold text-foreground">
              Gliederung überprüfen
            </div>
            <div className="text-sm text-muted-foreground mt-1">
              Lies jeden Abschnitt sorgfältig und bestätige, dass er korrekt
              ist.
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={onOpenCreate}
            className="shrink-0"
            disabled={isApplying || saving || isRefining || localRefining}
          >
            <Plus className="h-4 w-4 mr-2" />
            Neuer Entwurf
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4">
          {draftGroups.map((group, idx) => {
            const base = group.drafts[0];
            const baseSelected = selectedDraftSafe.id === base.id;
            const baseLabel = `Entwurf ${idx + 1}`;
            const baseRunning = base.status === "running";
            return (
              <div key={group.rootId} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => onSelectDraft(base.id)}
                  className={cn(
                    "h-9 px-3 rounded-md border text-sm transition-colors inline-flex items-center gap-2",
                    baseSelected
                      ? "border-primary bg-primary/5 text-foreground"
                      : "border-border bg-background hover:bg-muted/40 text-muted-foreground",
                  )}
                >
                  <span>{baseLabel}</span>
                  {baseRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" /> : null}
                </button>
                {group.drafts
                  .slice(1)
                  .map((d, i) => ({
                    draft: d,
                    version: Number((d as any).version ?? i + 2),
                  }))
                  .sort((a, b) => a.version - b.version)
                  .map(({ draft, version }) => {
                    const selected = selectedDraftSafe.id === draft.id;
                    return (
                      <button
                        key={draft.id}
                        type="button"
                        onClick={() => onSelectDraft(draft.id)}
                        className={cn(
                          "h-9 rounded-md border text-sm tabular-nums transition-colors inline-flex items-center justify-center gap-2 px-2.5",
                          selected
                            ? "border-primary bg-primary/5 text-foreground"
                            : "border-border bg-background hover:bg-muted/40 text-muted-foreground",
                        )}
                        aria-label={`Version ${version}`}
                        title={`Version ${version}`}
                      >
                        <span>{`v${version}`}</span>
                        {draft.status === "running" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                        ) : null}
                      </button>
                    );
                  })}
              </div>
            );
          })}
        </div>

        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5" />
          <span>
            Generiert mit {modelLabel}
            {selectedVersionNumber > 1
              ? ` – Version ${selectedVersionNumber}`
              : ""}
          </span>
          {saveError ? (
            <span className="text-destructive">· Nicht gespeichert</span>
          ) : null}
        </div>

        {selectedDraftSafe.status === "success" && output ? (
          <div className="mt-3 flex items-center gap-4">
            <Progress value={reviewProgress} className="h-1.5 flex-1" />
            <div className="text-sm text-muted-foreground tabular-nums">
              {reviewedCount}/{total}
            </div>
          </div>
        ) : (
          <div className="mt-3 flex items-center justify-end text-sm text-muted-foreground tabular-nums">
            {selectedDraftSafe.status === "running"
              ? "…"
              : selectedDraftSafe.status === "error"
                ? "Fehler"
                : ""}
          </div>
        )}

        {hasAnyNotices ? (
          <div className="mt-4 space-y-2">
            {hasStructuralBlockingErrors ? (
              <div className="flex items-start gap-2 text-sm text-destructive">
                <AlertTriangle className="h-4 w-4 mt-0.5" />
                <div>
                  <div className="font-medium">Bitte korrigieren</div>
                  <div className="text-destructive/90">
                    Ungültige Nummern (Format: 1 / 1.1 / 1.1.1) oder Tiefe &gt;
                    3 blockieren das Bestätigen.
                  </div>
                </div>
              </div>
            ) : null}

            {!hasStructuralBlockingErrors && hasDuplicateWarnings ? (
              <div className="flex items-start gap-2 text-sm text-yellow-700">
                <AlertTriangle className="h-4 w-4 mt-0.5" />
                <div>
                  <div className="font-medium">Hinweis</div>
                  <div className="text-yellow-800/90">
                    Es gibt doppelte Kapitelnummern. Du kannst trotzdem
                    fortfahren, solltest das aber prüfen.
                  </div>
                </div>
              </div>
            ) : null}

            {!hasStructuralBlockingErrors &&
            !hasDuplicateWarnings &&
            (validation.jumpWarnings.length > 0 ||
              validation.missingParentWarnings.length > 0) ? (
              <div className="flex items-start gap-2 text-sm text-muted-foreground">
                <AlertTriangle className="h-4 w-4 mt-0.5" />
                <div>
                  <div className="font-medium">Warnung</div>
                  <div>
                    Es gibt Nummerierungs‑Unstimmigkeiten. Das blockiert nicht.
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-8">
          <div className="max-w-[720px] mx-auto">
            {selectedDraftSafe.status === "running" ? (
              <div className="py-16 flex flex-col items-center text-center">
                <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
                <div className="mt-4 text-base font-medium text-foreground">
                  Gliederung wird erstellt…
                </div>
                <div className="mt-1 text-sm text-muted-foreground">
                  Sobald sie fertig ist, kannst du sie hier prüfen.
                </div>
              </div>
            ) : null}

            {selectedDraftSafe.status === "error" ? (
              <div className="py-12 flex flex-col items-center text-center">
                <div className="h-12 w-12 rounded-full bg-destructive/10 flex items-center justify-center">
                  <AlertTriangle className="h-5 w-5 text-destructive" />
                </div>
                <div className="mt-4 text-base font-medium text-foreground">
                  Entwurf konnte nicht erstellt werden
                </div>
                <div className="mt-1 text-sm text-muted-foreground max-w-[520px]">
                  {selectedDraftSafe.errorMessage || "Unbekannter Fehler."}
                </div>
                <div className="mt-5">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={onOpenCreate}
                  >
                    Neuer Entwurf
                  </Button>
                </div>
              </div>
            ) : null}

            {selectedDraftSafe.status === "success" && output ? (
              <div className="space-y-4">
                {sortedChapters.map((ch) => {
                  const hasDuplicate = validation.duplicateIds.has(ch.id);
                  const hasInvalid = validation.invalidIds.has(ch.id);
                  const isOpen = isKapitelOpen(ch.id);
                  const isEditing = editingKapitelId === ch.id;

                  const numberColor = hasInvalid
                    ? "text-destructive"
                    : hasDuplicate
                      ? "text-yellow-700"
                      : "text-muted-foreground";

                  const level = Math.min(
                    3,
                    Math.max(
                      1,
                      String(ch.nummer || "")
                        .trim()
                        .split(".")
                        .filter(Boolean).length || 1,
                    ),
                  );
                  const indentClass =
                    level === 1 ? "" : level === 2 ? "pl-4" : "pl-8";

                  return (
                    <div key={ch.id} className={indentClass}>
                      <div
                        className={cn(
                          "rounded-xl border bg-white shadow-sm transition-colors",
                          ch.reviewed
                            ? "bg-primary/5 border-primary/30"
                            : "border-border",
                          hasInvalid
                            ? "border-destructive/40"
                            : hasDuplicate
                              ? "border-yellow-500/30"
                              : "",
                        )}
                      >
                        <button
                          type="button"
                          onClick={() => toggleKapitelOpen(ch.id)}
                          disabled={isEditing}
                          className={cn(
                            "w-full px-6 py-5 flex items-center justify-between gap-4 text-left",
                            isEditing ? "cursor-default" : "cursor-pointer",
                          )}
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <div className="text-muted-foreground">
                              {isOpen ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                            </div>
                            <div className="flex items-center gap-3 min-w-0">
                              <span
                                className={cn(
                                  "text-sm font-mono shrink-0",
                                  numberColor,
                                )}
                              >
                                {String(ch.nummer || "").trim() || "—"}
                              </span>
                              <span className="text-base font-semibold text-foreground truncate">
                                {String(ch.titel || "").trim() || "Ohne Titel"}
                              </span>
                            </div>
                          </div>

                          {ch.reviewed ? (
                            <div className="h-6 w-6 rounded-full bg-primary flex items-center justify-center shrink-0">
                              <Check className="h-4 w-4 text-primary-foreground" />
                            </div>
                          ) : null}
                        </button>

                        {isOpen ? (
                          <div className="px-6 pb-5">
                            {isEditing ? (
                              <div className="pt-4 border-t">
                                <div className="grid grid-cols-[72px_1fr] gap-3">
                                  <Input
                                    value={editForm.nummer}
                                    onChange={(e) => {
                                      const next = e.target.value.replace(
                                        /\s+/g,
                                        "",
                                      );
                                      if (!isAllowedKapitelNummerInput(next))
                                        return;
                                      setEditForm((p) => ({
                                        ...p,
                                        nummer: next,
                                      }));
                                    }}
                                    onBlur={() =>
                                      setEditForm((p) => {
                                        const cleaned = p.nummer
                                          .replace(/\.$/, "")
                                          .trim();
                                        return cleaned === p.nummer
                                          ? p
                                          : { ...p, nummer: cleaned };
                                      })
                                    }
                                    className="font-mono"
                                    inputMode="decimal"
                                    placeholder="z.B. 1.2"
                                  />
                                  <Input
                                    value={editForm.titel}
                                    onChange={(e) =>
                                      setEditForm((p) => ({
                                        ...p,
                                        titel: e.target.value,
                                      }))
                                    }
                                    placeholder="Kapitelüberschrift"
                                  />
                                </div>
                                <Textarea
                                  value={editForm.beschreibung}
                                  onChange={(e) =>
                                    setEditForm((p) => ({
                                      ...p,
                                      beschreibung: e.target.value,
                                    }))
                                  }
                                  className="mt-3 min-h-[120px] resize-none"
                                  placeholder="Thema & Anweisungen…"
                                />

                                <div className="mt-4 flex items-center justify-end gap-3">
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    onClick={cancelEditKapitel}
                                  >
                                    Abbrechen
                                  </Button>
                                  <Button
                                    type="button"
                                    onClick={saveEditKapitel}
                                  >
                                    Speichern
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <div className="pt-4 border-t">
                                <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
                                  {String(ch.beschreibung || "").trim() || "—"}
                                </p>

                                <div className="mt-4 pt-4 border-t flex items-center justify-between gap-4">
                                  <div className="flex items-center gap-2">
                                    <Checkbox
                                      id={`reviewed-${ch.id}`}
                                      checked={ch.reviewed}
                                      onCheckedChange={(v) =>
                                        updateKapitel(ch.id, {
                                          reviewed: Boolean(v),
                                        })
                                      }
                                    />
                                    <label
                                      htmlFor={`reviewed-${ch.id}`}
                                      className="text-sm text-muted-foreground cursor-pointer"
                                    >
                                      {ch.reviewed
                                        ? "Überprüft"
                                        : "Als überprüft markieren"}
                                    </label>
                                  </div>

                                  <div className="flex items-center gap-2">
                                    <button
                                      type="button"
                                      onClick={() => startEditKapitel(ch)}
                                      className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
                                    >
                                      <Pencil className="h-4 w-4" />
                                      Bearbeiten
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setDeleteKapitelId(ch.id)}
                                      className="inline-flex items-center justify-center h-9 w-9 rounded-md text-destructive hover:bg-destructive/10"
                                      aria-label="Kapitel löschen"
                                      title="Kapitel löschen"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </button>
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })}

                <button
                  type="button"
                  onClick={addKapitelManually}
                  className="w-full rounded-xl border border-dashed border-border bg-background hover:bg-muted/40 transition-colors px-6 py-4 flex items-center justify-center gap-2 text-sm text-muted-foreground hover:text-foreground"
                >
                  <Plus className="h-4 w-4" />
                  Kapitel hinzufügen
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {selectedDraftSafe.status === "success" && output ? (
        <div className="border-t bg-background px-6 py-4">
          <div className="max-w-[720px] mx-auto">
            <div className="flex items-center gap-2">
              <div className="flex-1 h-10 rounded-md border bg-white px-3 flex items-center gap-2 focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary/40">
                <Input
                  value={refineMessage}
                  onChange={(e) => setRefineMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleRefine();
                    }
                  }}
                  placeholder="Änderungswünsche beschreiben..."
                  className="h-full border-0 bg-transparent shadow-none rounded-none p-0 focus-visible:ring-0 focus-visible:ring-offset-0"
                  disabled={saving || isApplying || isRefining || localRefining}
                />
              </div>
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={handleRefine}
                disabled={
                  saving ||
                  isApplying ||
                  isRefining ||
                  localRefining ||
                  refineMessage.trim().length === 0
                }
                className="h-10 w-10"
                aria-label="Änderungen senden"
                title="Änderungen senden"
              >
                {isRefining || localRefining ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <SendHorizontal className="h-4 w-4" />
                )}
              </Button>
            </div>

            <div className="mt-2 text-xs text-muted-foreground flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5" />
              <span>
                Änderungen erstellen eine neue Version. Der aktuelle Entwurf
                bleibt erhalten.
              </span>
            </div>

            <div className="mt-3 flex items-center justify-between gap-4">
              <div className="text-sm text-muted-foreground">
                {remainingToReview === 0
                  ? "Alles geprüft."
                  : `Noch ${remainingToReview} Kapitel zu überprüfen.`}
              </div>

              {(() => {
                const disabled =
                  isApplying ||
                  saving ||
                  isRefining ||
                  localRefining ||
                  !allReviewed ||
                  hasBlockingErrors ||
                  total === 0;
                const reasons: string[] = [];
                if (total === 0)
                  reasons.push("Füge mindestens ein Kapitel hinzu.");
                if (!allReviewed)
                  reasons.push(
                    `Markiere alle Kapitel als überprüft (${reviewedCount}/${total}).`,
                  );
                if (hasBlockingErrors)
                  reasons.push(
                    "Behebe ungültige Nummern (Format 1 / 1.1 / 1.1.1) und max. Ebene 3.",
                  );
                if (saving) reasons.push("Warte, bis gespeichert wurde.");
                if (isRefining || localRefining)
                  reasons.push("Warte, bis die neue Version erstellt ist.");
                if (isApplying) reasons.push("Kapitel werden gerade erstellt.");

                return (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        tabIndex={disabled ? 0 : -1}
                        className="inline-flex"
                      >
                        <Button
                          type="button"
                          onClick={handleApply}
                          disabled={disabled}
                          className="min-w-[220px]"
                        >
                          {isApplying ? (
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          ) : (
                            <Check className="h-4 w-4 mr-2" />
                          )}
                          Gliederung bestätigen
                        </Button>
                      </span>
                    </TooltipTrigger>
                    {disabled && reasons.length > 0 ? (
                      <TooltipContent
                        side="top"
                        sideOffset={8}
                        className="max-w-[360px]"
                      >
                        <div className="space-y-1">
                          <div className="font-medium">Noch nicht möglich</div>
                          <ul className="list-disc pl-4 space-y-0.5">
                            {reasons.map((r) => (
                              <li key={r}>{r}</li>
                            ))}
                          </ul>
                        </div>
                      </TooltipContent>
                    ) : null}
                  </Tooltip>
                );
              })()}
            </div>
          </div>
        </div>
      ) : null}

      <AlertDialog
        open={!!deleteKapitelId}
        onOpenChange={(open) => !open && setDeleteKapitelId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Kapitel löschen?</AlertDialogTitle>
            <AlertDialogDescription>
              Dieses Kapitel wird aus dem Entwurf entfernt. Du kannst es später
              manuell wieder hinzufügen.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!deleteKapitelId) return;
                deleteKapitel(deleteKapitelId);
                setDeleteKapitelId(null);
              }}
            >
              Löschen
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
