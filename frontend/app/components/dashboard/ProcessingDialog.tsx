"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { ChevronDown, FileText, Loader2, Play, Settings2, Wand2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { ProcessingSettings } from "@/app/types/ui"
import type {
  ActivePromptSelections,
  PromptStage,
  PromptTemplate,
  StageDefaultPromptTemplates,
  SystemPromptTemplateMeta,
} from "@/app/types/prompts"
import { DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY } from "@/app/lib/prompts/promptConfig"
import { cn } from "@/lib/utils"

const DEFAULT_PROCESSING_MODEL: ProcessingSettings["model"] =
  process.env.NODE_ENV === "production" ? "gpt-5.4" : "gpt-5-nano"

interface ProcessingDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kapitelTitle: string
  kapitelThema?: string
  quellenCount: number
  onProcess: (settings: ProcessingSettings) => Promise<void>
  askOnEachProcess: boolean
  promptTemplates: PromptTemplate[]
  systemPromptTemplates: SystemPromptTemplateMeta[]
  stageDefaults: StageDefaultPromptTemplates
  promptActive: ActivePromptSelections
  isProcessing: boolean
}

export function ProcessingDialog({
  open,
  onOpenChange,
  kapitelTitle,
  kapitelThema,
  quellenCount,
  onProcess,
  askOnEachProcess,
  promptTemplates,
  systemPromptTemplates,
  stageDefaults,
  promptActive,
  isProcessing,
}: ProcessingDialogProps) {
  const [settings, setSettings] = useState<ProcessingSettings>({
    model: DEFAULT_PROCESSING_MODEL,
    ueberschrift: kapitelTitle,
    thema: kapitelThema || "",
    grundlegendeInfos: "",
    directCombine: false,
  })
  const [additionalOptionsOpen, setAdditionalOptionsOpen] = useState(false)
  const prevOpenRef = useRef(open)
  const [promptChoice, setPromptChoice] = useState<Partial<Record<PromptStage, string>>>({
    process_quelle:
      (promptActive?.process_quelle as string | undefined) ||
      (stageDefaults?.process_quelle as string | undefined) ||
      DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY,
    combine:
      (promptActive?.combine as string | undefined) ||
      (stageDefaults?.combine as string | undefined) ||
      DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY,
  })
  const [hasTouchedPromptChoice, setHasTouchedPromptChoice] = useState(false)
  const [localProcessing, setLocalProcessing] = useState(false)

  const templatesByStage = useMemo(() => {
    return (stage: PromptStage) => promptTemplates.filter((tpl) => tpl.stage === stage)
  }, [promptTemplates])

  const systemTemplatesByStage = useMemo(() => {
    return (stage: PromptStage) =>
      systemPromptTemplates
        .filter((tpl) => tpl.stage === stage)
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
      process_quelle:
        (promptActive?.process_quelle as string | undefined) ||
        (stageDefaults?.process_quelle as string | undefined) ||
        DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY,
      combine:
        (promptActive?.combine as string | undefined) ||
        (stageDefaults?.combine as string | undefined) ||
        DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY,
    })
  }, [
    open,
    promptActive?.process_quelle,
    promptActive?.combine,
    stageDefaults?.process_quelle,
    stageDefaults?.combine,
    hasTouchedPromptChoice,
  ])

  useEffect(() => {
    const wasOpen = prevOpenRef.current
    prevOpenRef.current = open
    if (!open || wasOpen) return

    setSettings({
      model: DEFAULT_PROCESSING_MODEL,
      ueberschrift: kapitelTitle,
      thema: kapitelThema || "",
      grundlegendeInfos: "",
      directCombine: false,
    })
    setAdditionalOptionsOpen(false)
  }, [open, kapitelTitle, kapitelThema])

  const handleProcess = async () => {
    if (localProcessing || isProcessing) return
    setLocalProcessing(true)
    onOpenChange(false)
    try {
      await onProcess(showPromptSelectors ? { ...settings, promptChoice } : settings)
    } finally {
      setLocalProcessing(false)
    }
  }

  const handleOpenChange = (open: boolean) => {
    onOpenChange(open)
  }

  const showPromptSelectors = askOnEachProcess

  const modelGroups: Array<{
    group: string
    options: Array<{ value: ProcessingSettings["model"]; label: string; description: string }>
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

  const renderPromptSelect = (stage: PromptStage, label: string) => {
    const stageTemplates = templatesByStage(stage)
    const stageSystemTemplates = systemTemplatesByStage(stage)
    const hasSystemOptions = stageSystemTemplates.length > 0
    if (!hasSystemOptions && stageTemplates.length === 0) return null
    const value =
      promptChoice[stage] ||
      (stageDefaults?.[stage] as string | undefined) ||
      DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY
    return (
      <div className="space-y-2">
        <Label className="text-sm font-medium">{label}</Label>
        <Select
          value={value}
          onValueChange={(val) =>
            setPromptChoice((prev) => {
              setHasTouchedPromptChoice(true)
              return {
                ...prev,
                [stage]: val,
              }
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

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[560px] p-0 gap-0 max-h-[80vh] overflow-hidden">
        <DialogHeader className="px-6 pt-6 pb-4 border-b text-left">
          <DialogTitle>Kapitel verarbeiten</DialogTitle>
          <DialogDescription className="pt-1">{quellenCount} Quellen zugewiesen</DialogDescription>
        </DialogHeader>

        <div className="px-6 py-5 space-y-6 max-h-[60vh] overflow-y-auto">
          {/* Section 1: Kapitel Info */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <span>Kapitelinformationen</span>
              <span className="text-destructive" aria-hidden="true">*</span>
            </div>

            <div className="grid gap-4 pl-6">
              <div>
                <Label htmlFor="ueberschrift" className="text-sm font-medium">
                  Überschrift
                </Label>
                <Input
                  id="ueberschrift"
                  value={settings.ueberschrift}
                  onChange={(e) => setSettings({ ...settings, ueberschrift: e.target.value })}
                  placeholder="z.B. Einleitung"
                  className="mt-2"
                />
              </div>

              <div>
                <Label htmlFor="thema" className="text-sm font-medium">
                  Thema & Anweisungen
                </Label>
                <Textarea
                  id="thema"
                  value={settings.thema}
                  onChange={(e) => setSettings({ ...settings, thema: e.target.value })}
                  placeholder="Beschreibe, worum es in diesem Kapitel gehen soll und gib spezifische Anweisungen..."
                  className="mt-2 min-h-[110px] resize-none"
                />
              </div>

            </div>
          </div>

          <div className="border-t" />

          {/* Section 2: Processing Settings */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Settings2 className="h-4 w-4 text-muted-foreground" />
              Verarbeitungseinstellungen
            </div>

            <div className="grid gap-4 pl-6">
              <div>
                <Label className="text-sm font-medium">KI-Modell</Label>
                <div role="radiogroup" aria-label="KI-Modell" className="mt-2 space-y-3">
                  {modelGroups.map((group) => (
                    <div key={group.group}>
                      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">{group.group}</div>
                      <div className="grid grid-cols-3 gap-3">
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
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between py-3 px-4 border bg-muted/20 rounded-lg">
                <div className="flex items-center gap-3">
                  <Wand2 className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <div className="flex items-center gap-2">
                      <Label htmlFor="direct-combine" className="text-sm font-medium cursor-pointer">
                        Direkt kombinieren
                      </Label>
                      <span
                        className={cn(
                          "text-xs font-medium px-2 py-0.5 rounded-md border",
                          settings.directCombine
                            ? "border-border bg-muted/40 text-muted-foreground"
                            : "border-border bg-background text-muted-foreground"
                        )}
                      >
                        {settings.directCombine ? "Aktiviert" : "Deaktiviert"}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Erstellt sofort einen zusammenhaengenden Text
                    </p>
                  </div>
                </div>
                <Switch
                  id="direct-combine"
                  checked={settings.directCombine}
                  onCheckedChange={(checked) => setSettings({ ...settings, directCombine: checked })}
                />
              </div>

              <Collapsible open={additionalOptionsOpen} onOpenChange={setAdditionalOptionsOpen}>
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    className="w-full flex items-center justify-between py-2 px-4 rounded-lg hover:bg-muted/30 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-muted-foreground">Zusätzliche Optionen</span>
                      <span className="text-xs font-medium px-2 py-0.5 rounded-md border text-muted-foreground bg-background">
                        Optional
                      </span>
                    </div>
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 text-muted-foreground transition-transform",
                        additionalOptionsOpen && "rotate-180"
                      )}
                    />
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-3">
                  <div className="grid gap-4">
                    <div>
                      <Label htmlFor="grundlegende-infos" className="text-sm font-medium">
                        Grundlegende Informationen
                        <span className="text-muted-foreground font-normal ml-1">(optional)</span>
                      </Label>
                      <Textarea
                        id="grundlegende-infos"
                        value={settings.grundlegendeInfos}
                        onChange={(e) => setSettings({ ...settings, grundlegendeInfos: e.target.value })}
                        placeholder="Hintergrundinformationen, Kontext oder zusaetzliche Details, die bei der Verarbeitung beruecksichtigt werden sollen..."
                        className="mt-2 min-h-[90px] resize-none"
                      />
                    </div>

                    {showPromptSelectors && (
                      <div className="pt-4">
                        <div className="text-sm font-semibold">Custom Prompts</div>
                        <div className="mt-3 grid gap-4">
                          {renderPromptSelect("process_quelle", "Prompt für Quelle schreiben")}
                          {settings.directCombine && renderPromptSelect("combine", "Prompt für Kombinieren")}
                        </div>
                      </div>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          </div>
        </div>

        <DialogFooter className="px-6 py-4 border-t gap-2 sm:justify-between">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button
            onClick={handleProcess}
            disabled={
              quellenCount === 0 ||
              !settings.ueberschrift.trim() ||
              !settings.thema.trim() ||
              localProcessing ||
              isProcessing
            }
            className="min-w-[210px]"
          >
            {localProcessing || isProcessing ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Play className="h-4 w-4 mr-2" />
            )}
            Verarbeitung starten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
