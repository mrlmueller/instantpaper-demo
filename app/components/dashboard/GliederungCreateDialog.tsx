"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { FileText, Loader2, Play, Settings2, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { ActivePromptSelections, PromptStage, PromptTemplate, SystemPromptTemplateMeta } from "@/app/types/prompts"
import { cn } from "@/lib/utils"

export type GliederungModel = "gpt-5-nano" | "gpt-5-mini" | "gpt-5.2"

export interface GliederungGenerateSettings {
  model: GliederungModel
  aufgabenstellung: string
  gliederungStudienbriefMitSeiten: string
  extraKontext: string
  promptChoice?: Partial<Record<PromptStage, string | "default">>
}

const DEFAULT_GLIEDERUNG_MODEL: GliederungModel = process.env.NODE_ENV === "production" ? "gpt-5.2" : "gpt-5-nano"

interface GliederungCreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onGenerate: (settings: GliederungGenerateSettings) => Promise<void>
  askOnEachProcess: boolean
  promptTemplates: PromptTemplate[]
  systemPromptTemplates: SystemPromptTemplateMeta[]
  promptActive: ActivePromptSelections
  isGenerating: boolean
}

export function GliederungCreateDialog({
  open,
  onOpenChange,
  onGenerate,
  askOnEachProcess,
  promptTemplates,
  systemPromptTemplates,
  promptActive,
  isGenerating,
}: GliederungCreateDialogProps) {
  const [settings, setSettings] = useState<Omit<GliederungGenerateSettings, "promptChoice">>({
    model: DEFAULT_GLIEDERUNG_MODEL,
    aufgabenstellung: "",
    gliederungStudienbriefMitSeiten: "",
    extraKontext: "",
  })
  const [localGenerating, setLocalGenerating] = useState(false)
  const prevOpenRef = useRef(open)

  const [promptChoice, setPromptChoice] = useState<Partial<Record<PromptStage, string | "default">>>({
    gliederung: (promptActive?.gliederung as string | "default") || "default",
  })
  const [hasTouchedPromptChoice, setHasTouchedPromptChoice] = useState(false)

  const stageTemplates = useMemo(() => {
    return promptTemplates.filter((tpl) => tpl.stage === "gliederung")
  }, [promptTemplates])

  const stageSystemTemplates = useMemo(() => {
    return systemPromptTemplates
      .filter((tpl) => tpl.stage === "gliederung")
      .slice()
      .sort((a, b) => {
        const rank = (key: string) => (key === "default" ? 0 : key === "default_v2" ? 1 : 2)
        const ra = rank(a.templateKey)
        const rb = rank(b.templateKey)
        if (ra !== rb) return ra - rb
        return a.name.localeCompare(b.name, "de")
      })
  }, [systemPromptTemplates])

  useEffect(() => {
    if (!open) {
      setHasTouchedPromptChoice(false)
      return
    }
    if (hasTouchedPromptChoice) return
    setPromptChoice({
      gliederung: (promptActive?.gliederung as string | "default") || "default",
    })
  }, [open, promptActive?.gliederung, hasTouchedPromptChoice])

  useEffect(() => {
    const wasOpen = prevOpenRef.current
    prevOpenRef.current = open
    if (!open || wasOpen) return

    setSettings({
      model: DEFAULT_GLIEDERUNG_MODEL,
      aufgabenstellung: "",
      gliederungStudienbriefMitSeiten: "",
      extraKontext: "",
    })
  }, [open])

  const handleGenerate = async () => {
    if (localGenerating || isGenerating) return
    setLocalGenerating(true)
    onOpenChange(false)
    try {
      await onGenerate({
        ...settings,
        aufgabenstellung: settings.aufgabenstellung.trim(),
        gliederungStudienbriefMitSeiten: settings.gliederungStudienbriefMitSeiten.trim(),
        extraKontext: settings.extraKontext.trim(),
        promptChoice,
      })
    } finally {
      setLocalGenerating(false)
    }
  }

  const showPromptSelectors = askOnEachProcess

  const modelOptions: Array<{
    value: GliederungModel
    label: string
    description: string
  }> = [
    { value: "gpt-5-nano", label: "GPT-5 nano", description: "Schnell" },
    { value: "gpt-5-mini", label: "GPT-5 mini", description: "Ausgewogen" },
    { value: "gpt-5.2", label: "GPT-5.2", description: "Beste Qualität" },
  ]

  const renderPromptSelect = () => {
    const hasSystemOptions = stageSystemTemplates.length > 0
    if (!hasSystemOptions && stageTemplates.length === 0) return null
    const value = promptChoice.gliederung || "default"
    return (
      <div className="space-y-2">
        <Label className="text-sm font-medium">Prompt‑Vorlage</Label>
        <Select
          value={value}
          onValueChange={(val) =>
            setPromptChoice((prev) => {
              setHasTouchedPromptChoice(true)
              return { ...prev, gliederung: val as string | "default" }
            })
          }
        >
          <SelectTrigger className="mt-2">
            <SelectValue placeholder="System-Standard" />
          </SelectTrigger>
          <SelectContent>
            {stageSystemTemplates.map((tpl) => (
              <SelectItem key={`sys-${tpl.templateKey}`} value={tpl.templateKey}>
                <span className="text-muted-foreground">{tpl.name}</span>
              </SelectItem>
            ))}
            {stageTemplates.map((tpl) => (
              <SelectItem key={tpl.id} value={tpl.id}>
                {tpl.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  const canGenerate = settings.aufgabenstellung.trim().length >= 10 && !localGenerating && !isGenerating

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px] p-0 gap-0 max-h-[85vh] overflow-hidden">
        <DialogHeader className="px-6 pt-6 pb-4 border-b text-left">
          <DialogTitle className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            Gliederung erstellen
          </DialogTitle>
          <DialogDescription className="pt-1">
            Erstelle einen Entwurf, den du anschließend Schritt für Schritt prüfst und bearbeitest.
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 py-5 space-y-6 max-h-[65vh] overflow-y-auto">
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <span>Inputs</span>
              <span className="text-destructive" aria-hidden="true">
                *
              </span>
            </div>

            <div className="grid gap-4 pl-6">
              <div className="space-y-2">
                <Label htmlFor="aufgabenstellung" className="text-sm font-medium">
                  Aufgabenstellung / Thema
                </Label>
                <Textarea
                  id="aufgabenstellung"
                  value={settings.aufgabenstellung}
                  onChange={(e) => setSettings({ ...settings, aufgabenstellung: e.target.value })}
                  placeholder="Beschreibe, was du in der Arbeit bearbeiten sollst…"
                  className="min-h-[120px] resize-none"
                />
                <p className="text-xs text-muted-foreground">
                  Mindestens 10 Zeichen erforderlich ({settings.aufgabenstellung.trim().length} / 10)
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="studienbrief" className="text-sm font-medium">
                  Studienbrief‑Gliederung (mit Seiten)
                  <span className="text-muted-foreground font-normal ml-1">(optional)</span>
                </Label>
                <Textarea
                  id="studienbrief"
                  value={settings.gliederungStudienbriefMitSeiten}
                  onChange={(e) => setSettings({ ...settings, gliederungStudienbriefMitSeiten: e.target.value })}
                  placeholder="Kapitelnummern, Titel und Seitenangaben…"
                  className="min-h-[110px] resize-none"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="extra-kontext" className="text-sm font-medium">
                  Extra‑Kontext
                  <span className="text-muted-foreground font-normal ml-1">(optional)</span>
                </Label>
                <Textarea
                  id="extra-kontext"
                  value={settings.extraKontext}
                  onChange={(e) => setSettings({ ...settings, extraKontext: e.target.value })}
                  placeholder="Vorgaben, Rahmenbedingungen, Fallbeschreibung…"
                  className="min-h-[90px] resize-none"
                />
              </div>
            </div>
          </div>

          <div className="border-t" />

          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Settings2 className="h-4 w-4 text-muted-foreground" />
              Einstellungen
            </div>

            <div className="grid gap-4 pl-6">
              <div>
                <Label className="text-sm font-medium">KI‑Modell</Label>
                <div role="radiogroup" aria-label="KI‑Modell" className="mt-2 grid grid-cols-3 gap-3">
                  {modelOptions.map((opt) => {
                    const selected = settings.model === opt.value
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => setSettings({ ...settings, model: opt.value })}
                        className={cn(
                          "rounded-lg border px-3 py-2.5 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30",
                          selected ? "border-primary bg-primary/5" : "border-border bg-background hover:bg-muted/40"
                        )}
                      >
                        <div className="text-sm font-medium leading-tight">{opt.label}</div>
                        <div className="text-xs text-muted-foreground mt-0.5">{opt.description}</div>
                      </button>
                    )
                  })}
                </div>
              </div>

              {showPromptSelectors && renderPromptSelect()}
            </div>
          </div>
        </div>

        <DialogFooter className="px-6 py-4 border-t gap-2 sm:justify-between">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button onClick={handleGenerate} disabled={!canGenerate} className="min-w-[240px]">
            {localGenerating || isGenerating ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Play className="h-4 w-4 mr-2" />
            )}
            Entwurf erstellen
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

