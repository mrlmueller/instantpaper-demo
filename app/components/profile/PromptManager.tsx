"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { STAGE_CONFIG } from "@/app/lib/prompts/promptConfig";
 import type {
   ActivePromptSelections,
   PromptStage,
   PromptTemplate,
   SystemPromptPermissions,
   SystemPromptTemplateMeta,
 } from "@/app/types/prompts";
import { toast } from "sonner";
 import { Check, Copy, Eye, Info, Pencil, Plus, Star, StarOff, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";

type EditorState = {
  id?: string;
  name: string;
  instructions: string;
};

 type TemplatesResponse = {
   templates: PromptTemplate[];
   active: ActivePromptSelections;
   askOnEachProcess?: boolean;
   systemTemplates?: SystemPromptTemplateMeta[];
   systemPermissions?: SystemPromptPermissions;
 };

const stageOptions: { value: PromptStage; label: string }[] = [
  { value: "process_quelle", label: STAGE_CONFIG.process_quelle.label },
  { value: "combine", label: STAGE_CONFIG.combine.label },
  { value: "shorten", label: STAGE_CONFIG.shorten.label },
  { value: "lesefluss", label: STAGE_CONFIG.lesefluss.label },
  { value: "summary", label: STAGE_CONFIG.summary.label },
];

const stubInstructionsByStage: Record<PromptStage, string> = {
  process_quelle:
    "<Prompt entfernt>",
  combine:
    "[AUFGABE]\nTitel: {KAPITEL_TITEL}\nThema: {KAPITEL_BESCHREIBUNG}\n\n[ENTWÜRFE]\n{DRAFTS}",
  shorten:
    "<kapitel_titel>\n{KAPITEL_TITEL}\n</kapitel_titel>\n\n<kapitel_beschreibung>\n{KAPITEL_BESCHREIBUNG}\n</kapitel_beschreibung>\n\n<gliederung_und_kapitelzusammenfassungen>\n{GLIEDERUNG_SUMMARY}\n</gliederung_und_kapitelzusammenfassungen>\n\n<kapiteltext>\n{KAPITELTEXT}\n</kapiteltext>",
  lesefluss:
    "<aufgabenstellung>\n{AUFGABENSTELLUNG}\n</aufgabenstellung>\n\n<gliederung_und_kapitelzusammenfassungen>\n{GLIEDERUNG_SUMMARY}\n</gliederung_und_kapitelzusammenfassungen>\n\n<kapiteltext_zu_ueberarbeiten>\n{KAPITELTEXT}\n</kapiteltext_zu_ueberarbeiten>",
  summary: "### Aufgabe:\nText:\n{KAPITELTEXT}",
};

export function PromptManager() {
  const [stage, setStage] = useState<PromptStage>("process_quelle");
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [systemTemplates, setSystemTemplates] = useState<SystemPromptTemplateMeta[]>([]);
  const [canDuplicateSystemPrompts, setCanDuplicateSystemPrompts] = useState(false);
  const [active, setActive] = useState<ActivePromptSelections>({});
  const [editorOpen, setEditorOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState>({ name: "", instructions: "" });
  const [missingPlaceholders, setMissingPlaceholders] = useState<string[]>([]);
  const [askOnEachProcess, setAskOnEachProcess] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [copiedVar, setCopiedVar] = useState<string | null>(null);

  const filteredTemplates = useMemo(
    () => templates.filter((tpl) => tpl.stage === stage),
    [templates, stage]
  );

  const currentConfig = STAGE_CONFIG[stage];

  const computeMissing = (instructions: string, targetStage: PromptStage) =>
    STAGE_CONFIG[targetStage].requiredPlaceholders.filter((ph) => !instructions.includes(ph));

  const loadData = async () => {
    try {
      const res = await fetch("/api/prompt-templates", { cache: "no-store" });
      const data: TemplatesResponse = await res.json();
      if (!res.ok) throw new Error((data as any).error || "Konnte Prompts nicht laden.");
      setTemplates(data.templates);
      setSystemTemplates(Array.isArray(data.systemTemplates) ? data.systemTemplates : []);
      setCanDuplicateSystemPrompts(Boolean(data.systemPermissions?.canDuplicateSystemPrompts));
      setActive(data.active || {});
      setAskOnEachProcess(Boolean(data.askOnEachProcess));
    } catch (err: any) {
      toast.error("Prompts konnten nicht geladen werden", { description: err?.message });
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSave = async () => {
    const payload = {
      name: editor.name.trim(),
      instructions: editor.instructions.trim(),
      stage,
    };
    if (!payload.name || !payload.instructions) {
      toast.error("Name und Instructions dürfen nicht leer sein.");
      return;
    }

    const missing = computeMissing(payload.instructions, stage);
    setMissingPlaceholders(missing);
    if (missing.length > 0) {
      toast.error("Pflicht-Platzhalter fehlen", { description: missing.join(", ") });
      return;
    }

    try {
      const res = await fetch(editor.id ? `/api/prompt-templates/${editor.id}` : "/api/prompt-templates", {
        method: editor.id ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Speichern fehlgeschlagen.");
      toast.success(editor.id ? "Prompt aktualisiert" : "Prompt angelegt");
      setEditorOpen(false);
      setEditor({ name: "", instructions: "" });
      await loadData();
    } catch (err: any) {
      toast.error("Fehler beim Speichern", { description: err?.message });
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/prompt-templates/${id}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Löschen fehlgeschlagen.");
      toast.success("Prompt gelöscht");
      setConfirmDelete(null);
      await loadData();
    } catch (err: any) {
      toast.error("Fehler beim Löschen", { description: err?.message });
    }
  };

  const handleSetActive = async (templateId: string | "default", targetStage?: PromptStage) => {
    const s = targetStage ?? stage;
    try {
      const res = await fetch("/api/prompt-templates/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: s, templateId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Aktiv setzen fehlgeschlagen.");
      setActive((prev) => ({ ...prev, [s]: templateId }));
      toast.success(
        templateId === "default"
          ? "System-Standard verwendet"
          : templateId === "default_v2"
            ? "System-Standard (v2) verwendet"
            : "Aktives Prompt gesetzt"
      );
    } catch (err: any) {
      toast.error("Fehler beim Setzen", { description: err?.message });
    }
  };

  const handleDuplicateUserTemplate = async (tpl: PromptTemplate) => {
    const suffix = " (Kopie)";
    const maxLen = 80;
    let name = `${tpl.name}${suffix}`;
    if (name.length > maxLen) name = name.slice(0, maxLen).trim();

    try {
      const res = await fetch("/api/prompt-templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: tpl.stage, name, instructions: tpl.instructions }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Duplizieren fehlgeschlagen.");
      toast.success("Prompt dupliziert");
      await loadData();
    } catch (err: any) {
      toast.error("Fehler beim Duplizieren", { description: err?.message });
    }
  };

  const handleDuplicateSystemTemplate = async (targetStage: PromptStage, templateKey: string, name: string) => {
    if (!canDuplicateSystemPrompts) return;
    const suffix = " (Kopie)";
    const maxLen = 80;
    let copyName = `${name}${suffix}`;
    if (copyName.length > maxLen) copyName = copyName.slice(0, maxLen).trim();

    try {
      const res = await fetch("/api/system-prompt-templates/duplicate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: targetStage, templateKey, name: copyName }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Duplizieren fehlgeschlagen.");
      toast.success("System-Prompt kopiert");
      await loadData();
    } catch (err: any) {
      toast.error("Fehler beim Kopieren", { description: err?.message });
    }
  };

  const renderPreview = () => {
    const sample = currentConfig.sampleData;
    const fallbackStub = stubInstructionsByStage[stage];
    let text = editor.instructions || fallbackStub;
    Object.entries(sample).forEach(([key, value]) => {
      text = text.replaceAll(`{${key}}`, value);
    });
    return text;
  };

  const stageVariables = useMemo(() => {
    const req = STAGE_CONFIG[stage].requiredPlaceholders.map((p) => ({ name: p.replace(/[{}]/g, ""), required: true }));
    const opt = (STAGE_CONFIG[stage].optionalPlaceholders || []).map((p) => ({ name: p.replace(/[{}]/g, ""), required: false }));
    return [...req, ...opt];
  }, [stage]);

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex items-center justify-between">
          <div>
            <Label htmlFor="ask-on-process" className="text-sm font-medium cursor-pointer">
              Prompt bei jeder Verarbeitung auswählen
            </Label>
            <p className="text-xs text-muted-foreground mt-1">
              {askOnEachProcess
                ? "Du wirst bei jedem Schritt gefragt, welchen Prompt du verwenden möchtest."
                : "Es werden automatisch deine Standard-Prompts verwendet."}
            </p>
          </div>
          <Switch
            id="ask-on-process"
            checked={askOnEachProcess}
            onCheckedChange={async (checked) => {
              setAskOnEachProcess(checked);
              try {
                const res = await fetch("/api/prompt-templates/settings", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ askOnEachProcess: checked }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "Speichern fehlgeschlagen.");
                toast.success("Einstellung gespeichert");
              } catch (err: any) {
                setAskOnEachProcess(!checked);
                toast.error("Fehler beim Speichern", { description: err?.message });
              }
            }}
          />
        </div>
      </Card>

      <Tabs value={stage} onValueChange={(v) => setStage(v as PromptStage)}>
        <TabsList className="w-full flex-wrap h-auto gap-1 p-1">
          {stageOptions.map((opt) => {
            const count = templates.filter((t) => t.stage === opt.value).length;
            return (
              <TabsTrigger
                key={opt.value}
                value={opt.value}
                className="text-xs px-3 py-1.5 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
              >
                {opt.label}
                {count > 0 && (
                  <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[10px]">
                    {count}
                  </Badge>
                )}
              </TabsTrigger>
            );
          })}
        </TabsList>

        {stageOptions.map((opt) => {
          const stageConfig = STAGE_CONFIG[opt.value];
          const stageTemplates = templates.filter((t) => t.stage === opt.value);
          const stageSystemTemplates = systemTemplates
            .filter((t) => t.stage === opt.value)
            .slice()
            .sort((a, b) => {
              const rank = (key: string) => (key === "default" ? 0 : key === "default_v2" ? 1 : 2);
              const ra = rank(a.templateKey);
              const rb = rank(b.templateKey);
              if (ra !== rb) return ra - rb;
              return a.name.localeCompare(b.name, "de");
            });
          const activeId = active[opt.value];

          return (
            <TabsContent key={opt.value} value={opt.value} className="mt-4 space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">{stageConfig.tooltip}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Pflicht:{" "}
                    {stageConfig.requiredPlaceholders.length
                      ? stageConfig.requiredPlaceholders.join(", ")
                      : "Keine"}
                  </p>
                </div>
                <Button
                  size="sm"
                  onClick={() => {
                    setStage(opt.value);
                    setEditor({ name: "", instructions: stubInstructionsByStage[opt.value] });
                    setMissingPlaceholders([]);
                    setEditorOpen(true);
                  }}
                >
                  <Plus className="h-4 w-4 mr-1" />
                  Neuer Prompt
                </Button>
              </div>

              <div className="space-y-3">
                {stageSystemTemplates.map((sys) => {
                  const isActive =
                    sys.templateKey === "default"
                      ? !activeId || activeId === "default"
                      : activeId === sys.templateKey;
                  return (
                    <Card
                      key={`${opt.value}:${sys.templateKey}`}
                      className={cn("p-4 transition-colors", isActive && "ring-2 ring-primary/50 bg-primary/5")}
                    >
                      <div className="flex items-start gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <h4 className="font-medium text-sm text-foreground">{sys.name}</h4>
                            <Badge variant="outline" className="font-mono text-[10px]">
                              {sys.templateKey}
                            </Badge>
                            {isActive && (
                              <Badge variant="default" className="h-5 text-[10px]">
                                Standard
                              </Badge>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          {canDuplicateSystemPrompts && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => handleDuplicateSystemTemplate(opt.value, sys.templateKey, sys.name)}
                              title="In eigene Prompts kopieren"
                            >
                              <Copy className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => handleSetActive(sys.templateKey, opt.value)}
                            disabled={isActive}
                            title={isActive ? "Aktiv" : "Als Standard setzen"}
                          >
                            {isActive ? <Check className="h-4 w-4 text-primary" /> : <Star className="h-4 w-4" />}
                          </Button>
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>

              {stageTemplates.length === 0 ? (
                <Card className="p-6 text-center">
                  <p className="text-sm text-muted-foreground">
                    Du hast noch keine eigenen Prompts für diese Stufe erstellt.
                  </p>
                  {opt.value === "process_quelle" || opt.value === "combine" || opt.value === "summary" || opt.value === "shorten" || opt.value === "lesefluss" ? (
                    <p className="text-xs text-muted-foreground mt-1">
                      Wähle oben zwischen System-Standard und System-Standard (v2).
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground mt-1">
                      Der System-Standard wird automatisch verwendet.
                    </p>
                  )}
                </Card>
              ) : (
                <div className="space-y-3">
                  {stageTemplates.map((tpl) => {
                    const isDefault = activeId === tpl.id;
                    return (
                      <Card
                        key={tpl.id}
                        className={cn(
                          "p-4 transition-colors",
                          isDefault && "ring-2 ring-primary/50 bg-primary/5"
                        )}
                      >
                        <div className="flex items-start gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <h4 className="font-medium text-sm text-foreground">{tpl.name}</h4>
                              {isDefault && (
                                <Badge variant="default" className="h-5 text-[10px]">
                                  Standard
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground mt-1 line-clamp-2 font-mono">
                              {tpl.instructions.slice(0, 180)}...
                            </p>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => handleSetActive(isDefault ? "default" : tpl.id, opt.value)}
                              title={isDefault ? "Standard entfernen" : "Als Standard setzen"}
                            >
                              {isDefault ? <StarOff className="h-4 w-4 text-primary" /> : <Star className="h-4 w-4" />}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => {
                                setStage(opt.value);
                                setEditor({ id: tpl.id, name: tpl.name, instructions: tpl.instructions });
                                setMissingPlaceholders(computeMissing(tpl.instructions, opt.value));
                                setEditorOpen(true);
                              }}
                              title="Bearbeiten"
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => handleDuplicateUserTemplate(tpl)}
                              title="Duplizieren"
                            >
                              <Copy className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-destructive hover:text-destructive"
                              onClick={() => setConfirmDelete(tpl.id)}
                              title="Löschen"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      </Card>
                    );
                  })}
                </div>
              )}
            </TabsContent>
          );
        })}
      </Tabs>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent
          className="w-auto max-w-none"
          style={{ width: "70vw", maxWidth: "70vw", maxHeight: "92vh" }}
          showCloseButton={false}
        >
          <DialogHeader className="pb-4 border-b">
            <div className="flex items-start justify-between">
              <div>
                <DialogTitle className="text-lg">{editor.id ? "Prompt bearbeiten" : "Neuer Prompt"}</DialogTitle>
                <p className="text-sm text-muted-foreground mt-1">{STAGE_CONFIG[stage].label}</p>
              </div>
              <Button variant="ghost" size="icon" className="-mr-2 h-8 w-8" onClick={() => setEditorOpen(false)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </DialogHeader>
          <div className="flex gap-6 py-5 min-h-0 flex-1 overflow-hidden">
            {/* Variables panel on the left */}
            <div className="w-72 shrink-0 flex flex-col min-h-0">
              <div className="p-4 bg-muted/40 rounded-lg flex flex-col min-h-0 flex-1">
                <p className="text-sm font-medium text-foreground shrink-0">Verfügbare Variablen</p>
                <p className="text-xs text-muted-foreground mt-1 shrink-0">
                  Klicke auf eine Variable, um sie zu kopieren.
                </p>

                <div className="flex flex-wrap gap-2 mt-3 shrink-0">
                  {stageVariables.map((variable) => (
                    <button
                      key={variable.name}
                      onClick={() => {
                        navigator.clipboard.writeText(`{${variable.name}}`);
                        setCopiedVar(variable.name);
                        setTimeout(() => setCopiedVar(null), 1200);
                      }}
                      className={cn(
                        "inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-mono transition-colors",
                        variable.required
                          ? "bg-primary/10 text-primary hover:bg-primary/20"
                          : "bg-background text-muted-foreground hover:bg-muted",
                        copiedVar === variable.name && "ring-2 ring-primary"
                      )}
                    >
                      {`{${variable.name}}`}
                      {variable.required && <span className="text-[10px] font-sans text-primary">*</span>}
                      {copiedVar === variable.name && <Check className="h-3 w-3 ml-1" />}
                    </button>
                  ))}
                </div>

                <div className="mt-4 pt-4 border-t overflow-y-auto flex-1 min-h-0">
                  <p className="text-xs font-medium text-foreground mb-2">Beschreibungen</p>
                  <div className="text-xs text-muted-foreground space-y-2">
                    {stageVariables.map((variable) => (
                      <div key={variable.name} className="leading-relaxed">
                        <span className="font-mono text-foreground">{`{${variable.name}}`}</span>
                        {variable.required && <span className="text-primary ml-0.5">*</span>}
                      </div>
                    ))}
                  </div>
                </div>

                <p className="text-[10px] text-muted-foreground mt-4 pt-3 border-t shrink-0">
                  <span className="text-primary">*</span> = Erforderlich
                </p>
              </div>
            </div>

            {/* Editor on the right */}
            <div className="flex-1 flex flex-col min-w-0 min-h-0">
              <div className="mb-4 shrink-0">
                <Label htmlFor="prompt-name" className="text-sm">
                  Name
                </Label>
                <Input
                  id="prompt-name"
                  value={editor.name}
                  onChange={(e) => setEditor((prev) => ({ ...prev, name: e.target.value }))}
                  placeholder="z. B. Wissenschaftlicher Stil"
                  className="mt-1.5"
                />
              </div>

              <div className="flex-1 flex flex-col min-h-0">
                <div className="flex items-center justify-between mb-2 shrink-0">
                  <div className="flex items-center gap-2">
                    <Label htmlFor="prompt-instructions" className="text-sm">
                      Prompt-Text
                    </Label>
                    {missingPlaceholders.length > 0 && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Info className="h-4 w-4 text-amber-600" />
                          </TooltipTrigger>
                          <TooltipContent className="text-xs max-w-xs">
                            Fehlende Platzhalter: {missingPlaceholders.join(", ")}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => setShowPreview(!showPreview)}
                  >
                    <Eye className="h-3.5 w-3.5 mr-1" />
                    {showPreview ? "Editor" : "Vorschau"}
                  </Button>
                </div>

                {showPreview ? (
                  <div className="flex-1 p-4 bg-muted/30 rounded-lg border overflow-y-auto text-sm whitespace-pre-wrap max-h-[60vh]">
                    {renderPreview() || <span className="text-muted-foreground italic">Keine Vorschau verfügbar</span>}
                  </div>
                ) : (
                  <Textarea
                    id="prompt-instructions"
                    className="font-mono text-sm resize-none min-h-[200px] max-h-[60vh] overflow-auto"
                    value={editor.instructions}
                    onChange={(e) => {
                      const value = e.target.value;
                      setEditor((prev) => ({ ...prev, instructions: value }));
                      setMissingPlaceholders(computeMissing(value, stage));
                    }}
                    placeholder="Schreibe deinen Prompt hier..."
                  />
                )}

                {missingPlaceholders.length > 0 && (
                  <div className="flex items-start gap-2 p-3 bg-destructive/10 text-destructive rounded-lg mt-3 shrink-0">
                    <Info className="h-4 w-4 mt-0.5 shrink-0" />
                    <div className="text-sm">
                      <p className="font-medium">Erforderliche Variablen fehlen:</p>
                      <p className="mt-1">{missingPlaceholders.join(", ")}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          <DialogFooter className="pt-4 border-t gap-2">
            <Button variant="outline" onClick={() => setEditorOpen(false)}>
              Abbrechen
            </Button>
            <Button onClick={handleSave} disabled={!editor.name.trim() || !editor.instructions.trim() || missingPlaceholders.length > 0}>
              {editor.id ? "Speichern" : "Anlegen"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Prompt löschen?</AlertDialogTitle>
            <AlertDialogDescription>
              Dieses Prompt wird entfernt. Falls es aktiv war, fällt die Stage auf das Default zurück.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction onClick={() => confirmDelete && handleDelete(confirmDelete)}>
              Löschen
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
