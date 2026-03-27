"use client";

import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Archive, Check, Pencil, Plus, RefreshCw, RotateCcw } from "lucide-react";

import { DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY, STAGE_CONFIG } from "@/app/lib/prompts/promptConfig";
import type { PromptStage, StageDefaultPromptTemplates } from "@/app/types/prompts";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

type AdminSystemPromptTemplate = {
  stage: PromptStage;
  templateKey: string;
  name: string;
  instructions: string;
  systemPrompt: string | null;
  published: boolean;
  archived: boolean;
  createdAt: string | null;
  updatedAt: string | null;
};

type EditorState = {
  isNew: boolean;
  stage: PromptStage;
  templateKey: string;
  name: string;
  instructions: string;
  systemPrompt: string;
  published: boolean;
  archived: boolean;
};

type ConfirmAction =
  | { kind: "publish"; template: AdminSystemPromptTemplate }
  | { kind: "archive"; template: AdminSystemPromptTemplate }
  | { kind: "restore"; template: AdminSystemPromptTemplate };

const stageOptions: { value: PromptStage; label: string }[] = [
  { value: "process_quelle", label: STAGE_CONFIG.process_quelle.label },
  { value: "combine", label: STAGE_CONFIG.combine.label },
  { value: "shorten", label: STAGE_CONFIG.shorten.label },
  { value: "lesefluss", label: STAGE_CONFIG.lesefluss.label },
  { value: "summary", label: STAGE_CONFIG.summary.label },
  { value: "gliederung", label: STAGE_CONFIG.gliederung.label },
];

const TEMPLATE_KEY_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

function isPromptStage(value: unknown): value is PromptStage {
  return typeof value === "string" && stageOptions.some((s) => s.value === value);
}

function formatIso(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("de-DE");
  } catch {
    return iso;
  }
}

function normalizeTemplate(input: any): AdminSystemPromptTemplate | null {
  const stage = input?.stage;
  const templateKey = input?.templateKey;
  if (!isPromptStage(stage) || typeof templateKey !== "string") return null;

  return {
    stage,
    templateKey,
    name: typeof input?.name === "string" ? input.name : templateKey,
    instructions: typeof input?.instructions === "string" ? input.instructions : "",
    systemPrompt: typeof input?.systemPrompt === "string" ? input.systemPrompt : null,
    published: input?.published === true,
    archived: input?.archived === true,
    createdAt: typeof input?.createdAt === "string" ? input.createdAt : null,
    updatedAt: typeof input?.updatedAt === "string" ? input.updatedAt : null,
  };
}

function sortByUpdatedDesc(a: AdminSystemPromptTemplate, b: AdminSystemPromptTemplate) {
  const aKey = a.updatedAt || a.createdAt || "";
  const bKey = b.updatedAt || b.createdAt || "";
  return bKey.localeCompare(aKey, "de");
}

export function SystemPromptManager() {
  const [stage, setStage] = useState<PromptStage>("process_quelle");
  const [templates, setTemplates] = useState<AdminSystemPromptTemplate[]>([]);
  const [stageDefaults, setStageDefaults] = useState<StageDefaultPromptTemplates>({});
  const [isLoading, setIsLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isSavingDefault, setIsSavingDefault] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);

  const load = async () => {
    setIsLoading(true);
    try {
      const [templatesRes, defaultsRes] = await Promise.all([
        fetch("/api/admin/system-prompt-templates", { cache: "no-store" }),
        fetch("/api/admin/prompt-defaults", { cache: "no-store" }),
      ]);

      let normalized: AdminSystemPromptTemplate[] = [];
      let defaults: StageDefaultPromptTemplates = {};

      const templatesData = await templatesRes.json().catch(() => ({}));
      if (!templatesRes.ok) {
        throw new Error(templatesData.error || "Konnte System-Prompts nicht laden.");
      }

      const raw = Array.isArray(templatesData?.templates) ? templatesData.templates : [];
      normalized = raw.map(normalizeTemplate).filter(Boolean) as AdminSystemPromptTemplate[];
      normalized.sort((a, b) => {
        if (a.stage !== b.stage) return a.stage.localeCompare(b.stage, "de");
        if (a.archived !== b.archived) return a.archived ? 1 : -1;
        if (a.published !== b.published) return a.published ? -1 : 1;
        return sortByUpdatedDesc(a, b);
      });

      const defaultsData = await defaultsRes.json().catch(() => ({}));
      if (defaultsRes.ok) {
        const rawDefaults = defaultsData?.stageDefaults;
        if (rawDefaults && typeof rawDefaults === "object") {
          const next: StageDefaultPromptTemplates = {};
          for (const opt of stageOptions) {
            const value = (rawDefaults as any)[opt.value];
            if (typeof value === "string" && value.trim()) next[opt.value] = value.trim();
          }
          defaults = next;
        }
      } else {
        toast.error("Standard-Prompts", {
          description: defaultsData.error || "Konnte Standard-Prompts nicht laden.",
        });
      }

      setTemplates(normalized);
      setStageDefaults(defaults);
    } catch (err: any) {
      toast.error("System-Prompts", {
        description: err?.message || "Konnte System-Prompts nicht laden.",
      });
      setTemplates([]);
      setStageDefaults({});
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stageTemplates = useMemo(() => templates.filter((t) => t.stage === stage), [templates, stage]);
  const published = useMemo(
    () => stageTemplates.filter((t) => t.published && !t.archived).slice().sort(sortByUpdatedDesc),
    [stageTemplates]
  );
  const drafts = useMemo(
    () => stageTemplates.filter((t) => !t.published && !t.archived).slice().sort(sortByUpdatedDesc),
    [stageTemplates]
  );
  const archived = useMemo(
    () => stageTemplates.filter((t) => t.archived).slice().sort(sortByUpdatedDesc),
    [stageTemplates]
  );

  const defaultOptions = useMemo(() => {
    const items: { key: string; label: string }[] = [];
    const seen = new Set<string>();

    const add = (key: string, label: string) => {
      if (!key || seen.has(key)) return;
      seen.add(key);
      items.push({ key, label });
    };

    add(DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY, `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);

    const configured = stageDefaults[stage];
    const configuredTpl = configured ? stageTemplates.find((t) => t.templateKey === configured) : null;
    const configuredAvailable = configuredTpl ? configuredTpl.published && !configuredTpl.archived : false;
    if (configured && !configuredAvailable) {
      add(configured, `${configured} (nicht verfügbar)`);
    }

    for (const tpl of published) {
      add(tpl.templateKey, `${tpl.name} (${tpl.templateKey})`);
    }

    return items;
  }, [published, stage, stageDefaults, stageTemplates]);

  const effectiveStageDefaultKey = stageDefaults[stage] || DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY;
  const configuredDefaultKey = stageDefaults[stage];
  const configuredDefaultTemplate = configuredDefaultKey
    ? stageTemplates.find((t) => t.templateKey === configuredDefaultKey)
    : null;
  const configuredDefaultUnavailable = Boolean(
    configuredDefaultKey &&
      configuredDefaultTemplate &&
      (configuredDefaultTemplate.archived || !configuredDefaultTemplate.published)
  );
  const configuredDefaultMissing = Boolean(configuredDefaultKey && !configuredDefaultTemplate);

  const saveStageDefault = async (targetStage: PromptStage, nextKey: string) => {
    const prevKey = stageDefaults[targetStage];

    setStageDefaults((prev) => {
      const next = { ...prev };
      if (nextKey === DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY) {
        delete next[targetStage];
      } else {
        next[targetStage] = nextKey;
      }
      return next;
    });

    setIsSavingDefault(true);
    try {
      const res = await fetch("/api/admin/prompt-defaults", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stage: targetStage,
          templateKey: nextKey === DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY ? null : nextKey,
        }),
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Speichern fehlgeschlagen.");

      toast.success("Standard-Prompt gespeichert");
    } catch (err: any) {
      setStageDefaults((prev) => {
        const next = { ...prev };
        if (typeof prevKey === "string" && prevKey.trim()) {
          next[targetStage] = prevKey.trim();
        } else {
          delete next[targetStage];
        }
        return next;
      });

      toast.error("Standard-Prompt", {
        description: err?.message || "Speichern fehlgeschlagen.",
      });
    } finally {
      setIsSavingDefault(false);
    }
  };

  const missingPlaceholders = useMemo(() => {
    if (!editor) return [];
    return STAGE_CONFIG[editor.stage].requiredPlaceholders.filter((ph) => !editor.instructions.includes(ph));
  }, [editor]);

  const openNew = () => {
    setEditor({
      isNew: true,
      stage,
      templateKey: "",
      name: "",
      instructions: "",
      systemPrompt: "",
      published: false,
      archived: false,
    });
    setEditorOpen(true);
  };

  const openEdit = (tpl: AdminSystemPromptTemplate) => {
    setEditor({
      isNew: false,
      stage: tpl.stage,
      templateKey: tpl.templateKey,
      name: tpl.name,
      instructions: tpl.instructions,
      systemPrompt: tpl.systemPrompt || "",
      published: tpl.published,
      archived: tpl.archived,
    });
    setEditorOpen(true);
  };

  const save = async (state: EditorState) => {
    const name = state.name.trim();
    const templateKey = state.templateKey.trim();
    const instructions = state.instructions.replace(/\s+$/, "");
    const systemPrompt = state.systemPrompt.replace(/\s+$/, "");

    if (!name) throw new Error("Name ist erforderlich.");
    if (!templateKey) throw new Error("templateKey ist erforderlich.");
    if (!TEMPLATE_KEY_RE.test(templateKey)) {
      throw new Error("templateKey ungültig. Erlaubt: Buchstaben/Zahlen plus '-'/'_' (max. 64 Zeichen).");
    }
    if (!instructions.trim()) throw new Error("Instructions sind erforderlich.");

    const missing = STAGE_CONFIG[state.stage].requiredPlaceholders.filter((ph) => !instructions.includes(ph));
    if (missing.length > 0) throw new Error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);

    setIsSaving(true);
    try {
      const res = await fetch("/api/admin/system-prompt-templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stage: state.stage,
          templateKey,
          name,
          instructions,
          systemPrompt,
          published: Boolean(state.published),
          archived: Boolean(state.archived),
        }),
        cache: "no-store",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Speichern fehlgeschlagen.");

      toast.success("System-Prompt gespeichert");
      setEditorOpen(false);
      setEditor(null);
      await load();
    } finally {
      setIsSaving(false);
    }
  };

  const quickToggle = async (
    tpl: AdminSystemPromptTemplate,
    next: Partial<Pick<AdminSystemPromptTemplate, "published" | "archived">>
  ) => {
    try {
      await save({
        isNew: false,
        stage: tpl.stage,
        templateKey: tpl.templateKey,
        name: tpl.name,
        instructions: tpl.instructions,
        systemPrompt: tpl.systemPrompt || "",
        published: typeof next.published === "boolean" ? next.published : tpl.published,
        archived: typeof next.archived === "boolean" ? next.archived : tpl.archived,
      });
    } catch (err: any) {
      toast.error("Aktion fehlgeschlagen", {
        description: err?.message || "Unbekannter Fehler",
      });
    }
  };

  const requiredPlaceholders = STAGE_CONFIG[stage].requiredPlaceholders.join(", ");
  const stageCounts = useMemo(() => {
    const counts: Partial<Record<PromptStage, number>> = {};
    for (const opt of stageOptions) counts[opt.value] = 0;
    for (const t of templates) {
      if (t.archived) continue;
      counts[t.stage] = (counts[t.stage] || 0) + 1;
    }
    return counts;
  }, [templates]);

  const confirmMeta = useMemo(() => {
    if (!confirmAction) return null;
    const tpl = confirmAction.template;
    if (confirmAction.kind === "publish") {
      return {
        title: "Template veröffentlichen?",
        description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
        buttonLabel: "Veröffentlichen",
        buttonVariant: "default" as const,
      };
    }
    if (confirmAction.kind === "restore") {
      return {
        title: "Template wiederherstellen?",
        description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
        buttonLabel: "Wiederherstellen",
        buttonVariant: "outline" as const,
      };
    }
    return {
      title: "Template archivieren?",
      description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
      buttonLabel: "Archivieren",
      buttonVariant: "destructive" as const,
    };
  }, [confirmAction]);

  const runConfirmAction = async () => {
    if (!confirmAction) return;
    const tpl = confirmAction.template;

    if (confirmAction.kind === "publish") {
      await quickToggle(tpl, { published: true, archived: false });
    } else if (confirmAction.kind === "restore") {
      await quickToggle(tpl, { archived: false, published: false });
    } else {
      await quickToggle(tpl, { archived: true, published: false });
    }

    setConfirmAction(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-foreground">System Prompt Templates</h2>
          <p className="text-sm text-muted-foreground">Templates für alle Nutzer</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={load} disabled={isLoading}>
            <RefreshCw className="h-4 w-4" />
            Aktualisieren
          </Button>
          <Button size="sm" onClick={openNew} disabled={isLoading}>
            <Plus className="h-4 w-4" />
            Neu
          </Button>
        </div>
      </div>

      <div>
        <div className="flex flex-wrap items-center gap-6 border-b">
          {stageOptions.map((opt) => {
            const count = stageCounts[opt.value] || 0;
            const isActive = stage === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setStage(opt.value)}
                className={cn(
                  "flex items-center gap-2 pb-3 text-sm font-medium border-b-2 -mb-px transition-colors",
                  isActive
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                <span>{opt.label}</span>
                {count > 0 ? (
                  <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-semibold">
                    {count}
                  </Badge>
                ) : null}
              </button>
            );
          })}
        </div>

        <p className="mt-3 text-xs text-muted-foreground">
          Pflicht-Platzhalter: <span className="font-mono">{requiredPlaceholders}</span>
        </p>

        <div className="mt-4 rounded-lg border bg-background p-4 space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-0.5">
              <p className="text-sm font-semibold text-foreground">Fallback-Standard für diese Stage</p>
              <p className="text-xs text-muted-foreground">
                Gilt für alle Nutzer ohne eigenen Standard. Reihenfolge: Nutzer &gt; Admin &gt; App-Standard.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row sm:items-center gap-2">
              <Select
                value={effectiveStageDefaultKey}
                onValueChange={(value) => saveStageDefault(stage, value)}
                disabled={isSavingDefault}
              >
                <SelectTrigger className="w-full sm:w-[340px]" size="sm">
                  <SelectValue placeholder="Standard wählen" />
                </SelectTrigger>
                <SelectContent align="end">
                  {defaultOptions.map((opt) => (
                    <SelectItem key={opt.key} value={opt.key}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Button
                variant="outline"
                size="sm"
                onClick={() => saveStageDefault(stage, DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY)}
                disabled={!configuredDefaultKey || isSavingDefault}
              >
                <RotateCcw className="h-4 w-4" />
                Zurücksetzen
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="rounded-md px-2 py-0.5 font-mono text-[11px]">
              Effektiv: {effectiveStageDefaultKey}
            </Badge>
            {configuredDefaultKey ? (
              <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-[11px] font-semibold">
                Admin-Default gesetzt
              </Badge>
            ) : (
              <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-[11px] font-semibold">
                Kein Admin-Default (App-Standard)
              </Badge>
            )}

            {configuredDefaultMissing ? (
              <Badge
                variant="secondary"
                className="rounded-md px-2 py-0.5 text-[11px] font-semibold bg-amber-100 text-amber-800"
              >
                Konfiguriert, aber nicht gefunden → Fallback nutzt neuestes Template
              </Badge>
            ) : null}

            {configuredDefaultUnavailable ? (
              <Badge
                variant="secondary"
                className="rounded-md px-2 py-0.5 text-[11px] font-semibold bg-amber-100 text-amber-800"
              >
                Konfiguriert, aber nicht verfügbar → Fallback nutzt neuestes Template
              </Badge>
            ) : null}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="rounded-lg border bg-background p-6">
          <p className="text-sm text-muted-foreground">Lade System-Prompts.</p>
        </div>
      ) : (
        <div className="space-y-8">
          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Veröffentlicht ({published.length})
            </p>
            {published.length === 0 ? (
              <div className="rounded-lg border bg-background p-6">
                <p className="text-sm text-muted-foreground">Keine veröffentlichten Templates.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {published.map((tpl) => (
                  <div key={`${tpl.stage}:${tpl.templateKey}`} className="rounded-lg border bg-background shadow-sm px-4 py-3">
                    <div className="flex items-center justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground truncate">{tpl.name}</p>
                          <Badge variant="outline" className="rounded-md px-2 py-0.5 font-mono text-[11px]">
                            {tpl.templateKey}
                          </Badge>
                          <Badge className="rounded-md bg-primary text-primary-foreground px-2 py-0.5 text-[11px] font-semibold">
                            Published
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          Erstellt: {formatIso(tpl.createdAt)} • Aktualisiert: {formatIso(tpl.updatedAt)}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => openEdit(tpl)}
                          aria-label="Bearbeiten"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setConfirmAction({ kind: "archive", template: tpl })}
                          aria-label="Archivieren"
                        >
                          <Archive className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Entwürfe ({drafts.length})
            </p>
            {drafts.length === 0 ? (
              <div className="rounded-lg border bg-background p-6">
                <p className="text-sm text-muted-foreground">Keine Entwürfe.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {drafts.map((tpl) => (
                  <div key={`${tpl.stage}:${tpl.templateKey}`} className="rounded-lg border bg-background shadow-sm px-4 py-3">
                    <div className="flex items-center justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground truncate">{tpl.name}</p>
                          <Badge variant="outline" className="rounded-md px-2 py-0.5 font-mono text-[11px]">
                            {tpl.templateKey}
                          </Badge>
                          <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-[11px] font-semibold">
                            Draft
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          Erstellt: {formatIso(tpl.createdAt)} • Aktualisiert: {formatIso(tpl.updatedAt)}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => openEdit(tpl)}
                          aria-label="Bearbeiten"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setConfirmAction({ kind: "publish", template: tpl })}
                          aria-label="Veröffentlichen"
                        >
                          <Check className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setConfirmAction({ kind: "archive", template: tpl })}
                          aria-label="Archivieren"
                        >
                          <Archive className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Archiviert ({archived.length})
            </p>
            {archived.length === 0 ? (
              <div className="rounded-lg border bg-background p-6">
                <p className="text-sm text-muted-foreground">Keine archivierten Templates.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {archived.map((tpl) => (
                  <div key={`${tpl.stage}:${tpl.templateKey}`} className="rounded-lg border bg-muted/30 shadow-sm px-4 py-3">
                    <div className="flex items-center justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground truncate">{tpl.name}</p>
                          <Badge variant="outline" className="rounded-md px-2 py-0.5 font-mono text-[11px]">
                            {tpl.templateKey}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          Archiviert: {formatIso(tpl.updatedAt || tpl.createdAt)}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => openEdit(tpl)}
                          aria-label="Ansehen"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setConfirmAction({ kind: "restore", template: tpl })}
                          aria-label="Wiederherstellen"
                        >
                          <RotateCcw className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <Dialog open={editorOpen} onOpenChange={(open) => (!isSaving ? setEditorOpen(open) : null)}>
        <DialogContent className="h-[80vh] max-h-[80vh] sm:w-[90vw] sm:max-w-[90vw] flex flex-col">
          <DialogHeader>
            <DialogTitle>{editor?.isNew ? "Neuen System-Prompt erstellen" : "System-Prompt bearbeiten"}</DialogTitle>
          </DialogHeader>

          {editor ? (
            <div className="flex flex-col gap-5 flex-1 min-h-0 overflow-y-auto pr-1">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Stage</Label>
                  <Input value={STAGE_CONFIG[editor.stage].label} disabled />
                </div>
                <div className="space-y-2">
                  <Label>templateKey</Label>
                  <Input
                    value={editor.templateKey}
                    disabled={!editor.isNew}
                    onChange={(e) => setEditor((prev) => (prev ? { ...prev, templateKey: e.target.value } : prev))}
                    placeholder="z.B. default_v3"
                    className="font-mono"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label>Name</Label>
                <Input
                  value={editor.name}
                  onChange={(e) => setEditor((prev) => (prev ? { ...prev, name: e.target.value } : prev))}
                  placeholder="z.B. System-Standard (v3)"
                />
              </div>

              <div className="flex items-center justify-between gap-4">
                <div className="space-y-0.5">
                  <Label className="text-sm font-medium">Published</Label>
                  <p className="text-xs text-muted-foreground">Nur publizierte Templates sind für Nutzer sichtbar.</p>
                </div>
                <Switch
                  checked={editor.published}
                  onCheckedChange={(checked) => setEditor((prev) => (prev ? { ...prev, published: checked } : prev))}
                />
              </div>

              <div className="grid grid-cols-2 gap-4 flex-1 min-h-0">
                <div className="flex flex-col gap-2 min-h-0">
                  <Label>System Prompt (optional)</Label>
                  <Textarea
                    value={editor.systemPrompt}
                    onChange={(e) => setEditor((prev) => (prev ? { ...prev, systemPrompt: e.target.value } : prev))}
                    placeholder="System role message (optional)"
                    className="flex-1 min-h-0 font-mono text-xs resize-none"
                  />
                </div>

                <div className="flex flex-col gap-2 min-h-0">
                  <div className="flex items-center justify-between gap-4">
                    <Label>Instructions</Label>
                    {missingPlaceholders.length > 0 ? (
                      <Badge variant="secondary" className="text-[10px]">
                        Fehlende Platzhalter: {missingPlaceholders.join(", ")}
                      </Badge>
                    ) : (
                      <Badge className="bg-emerald-600 text-white hover:bg-emerald-600 text-[10px]">OK</Badge>
                    )}
                  </div>
                  <Textarea
                    value={editor.instructions}
                    onChange={(e) => setEditor((prev) => (prev ? { ...prev, instructions: e.target.value } : prev))}
                    placeholder="User instruction template"
                    className={cn(
                      "flex-1 min-h-0 font-mono text-xs resize-none",
                      missingPlaceholders.length > 0 && "border-amber-400 focus-visible:ring-amber-400"
                    )}
                  />
                </div>
              </div>
            </div>
          ) : null}

          <DialogFooter className="mt-4">
            <Button
              variant="outline"
              onClick={() => {
                if (isSaving) return;
                setEditorOpen(false);
                setEditor(null);
              }}
              disabled={isSaving}
            >
              Abbrechen
            </Button>
            <Button
              onClick={async () => {
                if (!editor) return;
                try {
                  await save(editor);
                } catch (err: any) {
                  toast.error("Speichern fehlgeschlagen", {
                    description: err?.message || "Unbekannter Fehler",
                  });
                }
              }}
              disabled={!editor || isSaving || missingPlaceholders.length > 0}
            >
              {isSaving ? "Speichern…" : "Speichern"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={Boolean(confirmAction)}
        onOpenChange={(open) => (!open && !isSaving ? setConfirmAction(null) : null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmMeta?.title || "Aktion bestätigen"}</AlertDialogTitle>
            <AlertDialogDescription>{confirmMeta?.description || ""}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSaving}>Abbrechen</AlertDialogCancel>
            <AlertDialogPrimitive.Action asChild>
              <Button variant={confirmMeta?.buttonVariant || "destructive"} onClick={runConfirmAction} disabled={isSaving}>
                {confirmMeta?.buttonLabel || "Bestätigen"}
              </Button>
            </AlertDialogPrimitive.Action>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

