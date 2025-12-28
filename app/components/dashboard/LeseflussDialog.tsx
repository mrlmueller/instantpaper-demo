"use client"

import { useEffect, useMemo, useState } from "react"
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
import { Sparkles, AlertCircle, MessageSquareText, ChevronRight, Loader2 } from "lucide-react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import type { Kapitel } from "@/app/types/ui"
import type { ActivePromptSelections, PromptStage, PromptTemplate } from "@/app/types/prompts"
import { getKapitelsWithShortenedText } from "@/app/actions/kapitels"

interface LeseflussDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  allKapitels: Kapitel[]
  currentKapitelId: string
  runModel: string
  onLesefluss: (
    contextKapitelIds: string[],
    aufgabenstellung: string,
    promptChoice?: Partial<Record<PromptStage, string | "default">>
  ) => Promise<void>
  askOnEachProcess: boolean
  promptTemplates: PromptTemplate[]
  promptActive: ActivePromptSelections
  isLeseflussLoading: boolean
}

export function LeseflussDialog({
  open,
  onOpenChange,
  allKapitels,
  currentKapitelId,
  runModel,
  onLesefluss,
  askOnEachProcess,
  promptTemplates,
  promptActive,
  isLeseflussLoading,
}: LeseflussDialogProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [aufgabenstellung, setAufgabenstellung] = useState("")
  const [shortenedAvailability, setShortenedAvailability] = useState<Record<string, boolean> | null>(null)
  const [shortenedAvailabilityLoading, setShortenedAvailabilityLoading] = useState(false)
  const [promptChoice, setPromptChoice] = useState<Partial<Record<PromptStage, string | "default">>>({
    summary: (promptActive?.summary as string | "default") || "default",
    lesefluss: (promptActive?.lesefluss as string | "default") || "default",
  })
  const [hasTouchedPromptChoice, setHasTouchedPromptChoice] = useState(false)
  const [localLeseflussLoading, setLocalLeseflussLoading] = useState(false)

  const sortedKapiteln = useMemo(() => {
    const list = allKapitels.filter((k) => k.id !== currentKapitelId)
    return list.sort((a, b) => {
      const partsA = a.nummer.split(".").map(Number)
      const partsB = b.nummer.split(".").map(Number)
      for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
        const numA = partsA[i] || 0
        const numB = partsB[i] || 0
        if (numA !== numB) return numA - numB
      }
      return 0
    })
  }, [allKapitels, currentKapitelId])

  useEffect(() => {
    if (!open) {
      setShortenedAvailability(null)
      setShortenedAvailabilityLoading(false)
      return
    }

    const ids = sortedKapiteln.map((k) => k.id)
    if (ids.length === 0) {
      setShortenedAvailability({})
      return
    }

    let cancelled = false
    setShortenedAvailabilityLoading(true)

    getKapitelsWithShortenedText(ids)
      .then((result) => {
        if (cancelled) return
        setShortenedAvailability(result)
      })
      .catch((err) => {
        console.error("Failed to check Kapitel shortened text availability", err)
        if (cancelled) return
        setShortenedAvailability({})
      })
      .finally(() => {
        if (cancelled) return
        setShortenedAvailabilityLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [open, sortedKapiteln])

  const hasShortenedText = (kapitelId: string) => {
    if (shortenedAvailabilityLoading || !shortenedAvailability) return false
    return Boolean(shortenedAvailability[kapitelId])
  }

  const toggleKapitel = (id: string) => {
    if (!hasShortenedText(id)) return
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]))
  }

  useEffect(() => {
    if (!open) {
      setHasTouchedPromptChoice(false)
      return
    }
    if (hasTouchedPromptChoice) return
    setPromptChoice({
      summary: (promptActive?.summary as string | "default") || "default",
      lesefluss: (promptActive?.lesefluss as string | "default") || "default",
    })
  }, [
    open,
    promptActive?.summary,
    promptActive?.lesefluss,
    hasTouchedPromptChoice,
  ])

  const handleSubmit = async () => {
    if (
      selectedIds.length === 0 ||
      aufgabenstellung.trim().length < 10 ||
      localLeseflussLoading ||
      isLeseflussLoading
    )
      return
    setLocalLeseflussLoading(true)
    onOpenChange(false)
    try {
      await onLesefluss(selectedIds, aufgabenstellung.trim(), promptChoice)
      setSelectedIds([])
      setAufgabenstellung("")
    } finally {
      setLocalLeseflussLoading(false)
    }
  }

  const getIndentLevel = (nummer: string) => nummer.split(".").length - 1
  const showPromptSelectors = askOnEachProcess

  const renderPromptSelect = (stage: PromptStage, label: string) => {
    const options = promptTemplates.filter((p) => p.stage === stage)
    return (
      <div className="space-y-2">
        <Label className="text-sm">Prompt für {label}</Label>
        <Select
          value={promptChoice[stage] || "default"}
          onValueChange={(val) =>
            setPromptChoice((prev) => {
              setHasTouchedPromptChoice(true)
              return {
                ...prev,
                [stage]: val as string | "default",
              }
            })
          }
        >
          <SelectTrigger className="mt-1.5">
            <SelectValue placeholder="System-Standard" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="default">
              <span className="text-muted-foreground">System-Standard</span>
            </SelectItem>
            {stage === "summary" && (
              <SelectItem value="default_v2">
                <span className="text-muted-foreground">System-Standard (v2)</span>
              </SelectItem>
            )}
            {options.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[70vh] [&>button]:hidden">
        <DialogHeader className="pb-4 border-b">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            Lesefluss verbessern
          </DialogTitle>
          <DialogDescription className="pt-1">
            Wähle andere Kapitel als Kontext, um den Lesefluss konsistent zu verbessern
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4 max-h-[60vh] overflow-y-auto">
          {showPromptSelectors && (
            <div className="pb-4 border-b space-y-4">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <MessageSquareText className="h-4 w-4" />
                Prompts
              </div>
              <div className="grid gap-4">
                {renderPromptSelect("summary", "Zusammenfassung")}
                {renderPromptSelect("lesefluss", "Lesefluss")}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="aufgabenstellung">Aufgabenstellung für die gesamte Arbeit</Label>
            <Textarea
              id="aufgabenstellung"
              placeholder="z.B. Analyse der Auswirkungen von KI auf die Arbeitswelt..."
              value={aufgabenstellung}
              onChange={(e) => setAufgabenstellung(e.target.value)}
              rows={5}
              className="resize-none"
            />
            <p className="text-xs text-muted-foreground">Mindestens 10 Zeichen erforderlich ({aufgabenstellung.length} / 10)</p>
          </div>

          <div className="space-y-2">
            <Label>Kontext-Kapitel auswählen</Label>
            <p className="text-sm text-muted-foreground">
              Wähle andere Kapitel aus, die als Kontext verwendet werden sollen. Nur Kapitel mit gekürztem Text können ausgewählt werden.
            </p>
            <div className="border rounded-lg max-h-[240px] overflow-y-auto">
                <TooltipProvider>
                  {sortedKapiteln.map((kapitel) => {
                  const isLoading = shortenedAvailabilityLoading || !shortenedAvailability
                  const hasShortened = !isLoading && Boolean(shortenedAvailability[kapitel.id])
                  const isSelected = selectedIds.includes(kapitel.id)
                  const indentLevel = getIndentLevel(kapitel.nummer)

                  return (
                    <Tooltip key={kapitel.id}>
                      <TooltipTrigger asChild>
                        <button
                          className={cn(
                            "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors border-b last:border-b-0",
                            hasShortened && "hover:bg-muted/50 cursor-pointer",
                            !hasShortened && "opacity-50 cursor-not-allowed",
                            isSelected && "bg-primary/10",
                          )}
                          onClick={() => toggleKapitel(kapitel.id)}
                          disabled={isLoading || !hasShortened}
                          style={{ paddingLeft: `${16 + indentLevel * 20}px` }}
                        >
                          <div
                            className={cn(
                              "w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors",
                              isSelected
                                ? "bg-primary border-primary text-primary-foreground"
                                : hasShortened
                                  ? "border-muted-foreground/30"
                                  : "border-muted-foreground/20 bg-muted/30",
                            )}
                          >
                            {isSelected && <ChevronRight className="h-3 w-3" />}
                          </div>
                          <div className="flex-1 min-w-0">
                            <span className="text-sm">
                              <span className="text-muted-foreground mr-1.5">{kapitel.nummer}</span>
                              <span className={cn(!hasShortened && "text-muted-foreground")}>{kapitel.title}</span>
                            </span>
                          </div>
                          {!hasShortened && <AlertCircle className="h-4 w-4 text-muted-foreground/50 shrink-0" />}
                        </button>
                      </TooltipTrigger>
                      {!hasShortened && (
                        <TooltipContent side="left">
                          <p>
                            {isLoading ? "Pr\u00fcfe Text\u2026" : "Dieses Kapitel hat noch keinen gek\u00fcrzten Text"}
                          </p>
                        </TooltipContent>
                      )}
                    </Tooltip>
                  )
                })}
              </TooltipProvider>
            </div>
            {selectedIds.length > 0 && (
              <p className="text-xs text-muted-foreground">{selectedIds.length} Kapitel ausgewählt</p>
            )}
          </div>

          {/* Model is fixed per run; don't show it in the dialog. */}
        </div>

        <DialogFooter className="pt-4 border-t gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={
              selectedIds.length === 0 ||
              aufgabenstellung.trim().length < 10 ||
              localLeseflussLoading ||
              isLeseflussLoading
            }
          >
            {localLeseflussLoading || isLeseflussLoading ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4 mr-2" />
            )}
            Lesefluss verbessern ({selectedIds.length} Kontext)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
