"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { STAGE_CONFIG } from "@/app/lib/prompts/promptConfig";
import type { ActivePromptSelections, PromptStage, PromptTemplate } from "@/app/types/prompts";
import { toast } from "sonner";
import { Info } from "lucide-react";

type TemplatesResponse = { templates: PromptTemplate[]; active: ActivePromptSelections };

type EditorState = {
  id?: string;
  name: string;
  instructions: string;
};

const stageOptions: { value: PromptStage; label: string }[] = [
  { value: "process_quelle", label: STAGE_CONFIG.process_quelle.label },
  { value: "combine", label: STAGE_CONFIG.combine.label },
  { value: "shorten", label: STAGE_CONFIG.shorten.label },
  { value: "lesefluss", label: STAGE_CONFIG.lesefluss.label },
  { value: "summary", label: STAGE_CONFIG.summary.label },
];

export function PromptManager() {
  const [stage, setStage] = useState<PromptStage>("process_quelle");
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [active, setActive] = useState<ActivePromptSelections>({});
  const [loading, setLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState>({ name: "", instructions: "" });
  const [missingPlaceholders, setMissingPlaceholders] = useState<string[]>([]);

  const filteredTemplates = useMemo(
    () => templates.filter((tpl) => tpl.stage === stage),
    [templates, stage]
  );

  const currentConfig = STAGE_CONFIG[stage];
  const stubInstructionsByStage: Record<PromptStage, string> = {
    process_quelle: "### Aufgabe:\nHeading: {heading}\nThema: {topic}",
    combine: "### Aufgabe:\nHeading: {heading}\nThema: {topic}",
    shorten: "### Aufgabe:\nUeberschrift: {ueberschrift}\nThema: {thema}",
    lesefluss: "### Aufgabe:\nAufgabenstellung: {aufgabenstellung}\nKapitel: {kapitel_nummer}",
    summary: "### Aufgabe:\nText: {text}",
  };

  const computeMissing = (instructions: string) =>
    currentConfig.requiredPlaceholders.filter((ph) => !instructions.includes(ph));

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/prompt-templates");
      const data: TemplatesResponse = await res.json();
      if (!res.ok) throw new Error((data as any).error || "Konnte Prompts nicht laden.");
      setTemplates(data.templates);
      setActive(data.active || {});
    } catch (err: any) {
      toast.error("Prompts konnten nicht geladen werden", { description: err?.message });
    } finally {
      setLoading(false);
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

    const missing = computeMissing(payload.instructions);
    setMissingPlaceholders(missing);
    if (missing.length > 0) {
      toast.error("Pflicht-Platzhalter fehlen", {
        description: missing.join(", "),
      });
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

  const handleSetActive = async (templateId: string | "default") => {
    try {
      const res = await fetch("/api/prompt-templates/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage, templateId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Aktiv setzen fehlgeschlagen.");
      setActive((prev) => ({ ...prev, [stage]: templateId }));
      toast.success("Aktives Prompt gesetzt");
    } catch (err: any) {
      toast.error("Fehler beim Setzen", { description: err?.message });
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

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-4 mb-4">
        <div>
          <p className="text-sm text-muted-foreground">Aktives Prompt pro Stage festlegen</p>
          <h3 className="text-lg font-semibold">Prompts verwalten</h3>
        </div>
        <Select value={stage} onValueChange={(val) => setStage(val as PromptStage)}>
          <SelectTrigger className="w-[240px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {stageOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2 text-sm text-muted-foreground mb-4">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Info className="h-4 w-4" />
            </TooltipTrigger>
            <TooltipContent className="max-w-sm text-xs">
              <p>{currentConfig.tooltip}</p>
              {currentConfig.optionalPlaceholders && (
                <p className="mt-2">
                  Optional: {currentConfig.optionalPlaceholders.join(", ")}
                </p>
              )}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <span>Max. {filteredTemplates.length}/10 Templates für {currentConfig.label}</span>
      </div>

      <div className="space-y-3">
        <Card className="p-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Badge variant="outline">Default</Badge>
            <div>
              <p className="font-medium text-sm">Unsichtbares System-Default</p>
              <p className="text-xs text-muted-foreground">
                Wird verwendet, wenn kein eigenes Prompt aktiv ist.
              </p>
            </div>
          </div>
          <Button
            variant={active[stage] === "default" || !active[stage] ? "default" : "outline"}
            size="sm"
            onClick={() => handleSetActive("default")}
          >
            {active[stage] === "default" || !active[stage] ? "Aktiv" : "Als aktiv setzen"}
          </Button>
        </Card>

        {filteredTemplates.map((tpl) => (
          <Card key={tpl.id} className="p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-medium">{tpl.name}</p>
                <p className="text-xs text-muted-foreground">
                  Platzhalter: {tpl.placeholders?.length ? tpl.placeholders.join(", ") : "–"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant={active[stage] === tpl.id ? "default" : "outline"}
                  size="sm"
                  onClick={() => handleSetActive(tpl.id)}
                >
                  {active[stage] === tpl.id ? "Aktiv" : "Aktiv setzen"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setEditor({ id: tpl.id, name: tpl.name, instructions: tpl.instructions });
                    setEditorOpen(true);
                  }}
                >
                  Bearbeiten
                </Button>
                <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(tpl.id)}>
                  Löschen
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            Pflicht-Platzhalter:{" "}
            {currentConfig.requiredPlaceholders.length
              ? currentConfig.requiredPlaceholders.join(", ")
              : "Keine"}
          </p>
        </div>
        <Button
          onClick={() => {
            setEditor({ name: "", instructions: stubInstructionsByStage[stage] });
            setMissingPlaceholders([]);
            setEditorOpen(true);
          }}
        >
          Neues Prompt
        </Button>
      </div>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent
          className="w-auto max-w-none"
          style={{ width: "70vw", maxWidth: "70vw", maxHeight: "92vh" }}
        >
          <DialogHeader>
            <DialogTitle>{editor.id ? "Prompt bearbeiten" : "Neues Prompt"}</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-3">
              <div>
                <Label htmlFor="prompt-name">Name</Label>
                <Input
                  id="prompt-name"
                  value={editor.name}
                  onChange={(e) => setEditor((prev) => ({ ...prev, name: e.target.value }))}
                  placeholder="z. B. Aggressiv kürzen"
                />
              </div>
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Label htmlFor="prompt-instructions">Instructions</Label>
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
                <Textarea
                  id="prompt-instructions"
                  className="h-[60vh] resize-none overflow-auto"
                  value={editor.instructions}
                  onChange={(e) => {
                    const value = e.target.value;
                    setEditor((prev) => ({ ...prev, instructions: value }));
                    setMissingPlaceholders(computeMissing(value));
                  }}
                />
                {missingPlaceholders.length > 0 && (
                  <p className="text-xs text-amber-700">
                    Fehlende Platzhalter: {missingPlaceholders.join(", ")}
                  </p>
                )}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Sandbox-Preview (mit Beispielwerten)</Label>
              <Card className="p-3 h-[60vh] overflow-y-auto bg-muted/50">
                <pre className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/80">
                  {renderPreview()}
                </pre>
              </Card>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditorOpen(false)}>
              Abbrechen
            </Button>
            <Button onClick={handleSave}>{editor.id ? "Speichern" : "Anlegen"}</Button>
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
    </Card>
  );
}
