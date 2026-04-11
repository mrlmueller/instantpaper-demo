"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeft, Loader2, Sparkles, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type {
  ActivePromptSelections,
  PromptStage,
  PromptTemplate,
  StageDefaultPromptTemplates,
  SystemPromptTemplateMeta,
} from "@/app/types/prompts"
import { DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY } from "@/app/lib/prompts/promptConfig"
import { cn } from "@/lib/utils"
import type { ProcessingSettings } from "@/app/types/ui"

export type GliederungModel = ProcessingSettings["model"]

export interface GliederungGenerateSettings {
  model: GliederungModel
  aufgabenstellung: string
  gliederungStudienbriefMitSeiten: string
  extraKontext: string
  promptChoice?: Partial<Record<PromptStage, string>>
}

const DEFAULT_GLIEDERUNG_MODEL: GliederungModel = process.env.NODE_ENV === "production" ? "gpt-5.4" : "gpt-5-nano"

interface GliederungCreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onGenerate: (settings: GliederungGenerateSettings) => Promise<void>
  askOnEachProcess: boolean
  promptTemplates: PromptTemplate[]
  systemPromptTemplates: SystemPromptTemplateMeta[]
  stageDefaults: StageDefaultPromptTemplates
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
  stageDefaults,
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

  const [promptChoice, setPromptChoice] = useState<Partial<Record<PromptStage, string>>>({
    gliederung:
      (promptActive?.gliederung as string | undefined) ||
      (stageDefaults?.gliederung as string | undefined) ||
      DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY,
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
      gliederung:
        (promptActive?.gliederung as string | undefined) ||
        (stageDefaults?.gliederung as string | undefined) ||
        DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY,
    })
  }, [open, promptActive?.gliederung, stageDefaults?.gliederung, hasTouchedPromptChoice])

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
        ...(showPromptSelectors ? { promptChoice } : {}),
      })
    } finally {
      setLocalGenerating(false)
    }
  }

  const showPromptSelectors = askOnEachProcess

  const modelGroups: Array<{
    group: string
    options: Array<{ value: GliederungModel; label: string; description: string }>
  }> = [
    {
      group: "OpenAI",
      options: [
        { value: "gpt-5-nano", label: "GPT-5 nano", description: "Schnell" },
        { value: "gpt-5-mini", label: "GPT-5 mini", description: "Ausgewogen" },
        { value: "gpt-5.4", label: "GPT-5.4", description: "Beste Qualität" },
      ],
    },
    {
      group: "Claude",
      options: [
        { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6", description: "Ausgewogen" },
        { value: "claude-opus-4-6", label: "Claude Opus 4.6", description: "Beste Qualität" },
      ],
    },
  ]

  const renderPromptSelect = () => {
    const hasSystemOptions = stageSystemTemplates.length > 0
    if (!hasSystemOptions && stageTemplates.length === 0) return null
    const value =
      promptChoice.gliederung ||
      (stageDefaults?.gliederung as string | undefined) ||
      DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY
    return (
      <div className="space-y-2">
        <Label className="text-sm font-medium">Prompt‑Vorlage</Label>
        <Select
          value={value}
          onValueChange={(val) =>
            setPromptChoice((prev) => {
              setHasTouchedPromptChoice(true)
              return { ...prev, gliederung: val }
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
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-[720px] p-0 gap-0 max-h-[85vh] overflow-hidden ring-2 ring-primary/40"
      >
        <DialogTitle className="sr-only">Gliederung generieren</DialogTitle>
        <div className="px-6 pt-5 pb-4 border-b">
          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="h-8 w-8 rounded-md hover:bg-muted flex items-center justify-center"
              aria-label="Zurück"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div className="flex-1 text-left">
              <div className="text-lg font-semibold text-foreground">Gliederung generieren</div>
            </div>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="h-8 w-8 rounded-md hover:bg-muted flex items-center justify-center"
              aria-label="Schließen"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="px-6 py-5 space-y-5 max-h-[65vh] overflow-y-auto">
          <div className="space-y-2">
            <Label htmlFor="aufgabenstellung" className="text-sm font-medium">
              Aufgabenstellung <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="aufgabenstellung"
              value={settings.aufgabenstellung}
              onChange={(e) => setSettings({ ...settings, aufgabenstellung: e.target.value })}
              placeholder="Füge hier die vollständige Aufgabenstellung deiner Arbeit ein..."
              className="min-h-[120px] resize-none"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="extra-kontext" className="text-sm font-medium">
              Zusätzliche Informationen
            </Label>
            <Textarea
              id="extra-kontext"
              value={settings.extraKontext}
              onChange={(e) => setSettings({ ...settings, extraKontext: e.target.value })}
              placeholder="Weitere Hinweise, Anforderungen oder Kontext..."
              className="min-h-[90px] resize-none"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="studienbrief" className="text-sm font-medium">
              Gliederung aus Studienbrief
            </Label>
            <Textarea
              id="studienbrief"
              value={settings.gliederungStudienbriefMitSeiten}
              onChange={(e) => setSettings({ ...settings, gliederungStudienbriefMitSeiten: e.target.value })}
              placeholder="Falls vorhanden, füge hier eine vorgegebene Gliederungsstruktur ein..."
              className="min-h-[90px] resize-none"
            />
          </div>

          <div className="space-y-2">
            <Label className="text-sm font-medium">KI‑Modell</Label>
            <div role="radiogroup" aria-label="KI‑Modell" className="mt-2 space-y-3">
              {modelGroups.map((group) => (
                <div key={group.group}>
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">{group.group}</div>
                  <div className={cn("grid gap-3", group.options.length === 2 ? "grid-cols-2" : "grid-cols-3")}>
                    {group.options.map((opt) => {
                      const selected = settings.model === opt.value
                      return (
                        <button
                          key={opt.value}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          onClick={() => setSettings({ ...settings, model: opt.value })}
                          className={cn(
                            "rounded-lg border px-3 py-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30",
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
              ))}
            </div>
          </div>

          {showPromptSelectors ? renderPromptSelect() : null}
        </div>

        <div className="px-6 py-4 border-t flex items-center justify-end">
          <Button onClick={handleGenerate} disabled={!canGenerate} className="min-w-[160px]">
            {localGenerating || isGenerating ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Sparkles className="h-4 w-4 mr-2" />}
            Generieren
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
