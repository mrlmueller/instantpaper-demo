"use client"

import { useEffect, useMemo, useState } from "react"
import { Scissors, ChevronRight, AlertCircle, MessageSquareText, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import type { Kapitel } from "@/app/types/ui"
import type { ActivePromptSelections, PromptStage, PromptTemplate, SystemPromptTemplateMeta } from "@/app/types/prompts"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { getKapitelsWithCombinedText } from "@/app/actions/kapitels"

interface ShortenDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  allKapitels: Kapitel[]
  currentKapitelId: string
  runModel: string
  onShorten: (
    contextKapitelIds: string[],
    promptChoice?: Partial<Record<PromptStage, string | "default">>
  ) => Promise<void>
  askOnEachProcess: boolean
  promptTemplates: PromptTemplate[]
  systemPromptTemplates: SystemPromptTemplateMeta[]
  promptActive: ActivePromptSelections
  isShortening: boolean
}

export function ShortenDialog({
  open,
  onOpenChange,
  allKapitels,
  currentKapitelId,
  runModel,
  onShorten,
  askOnEachProcess,
  promptTemplates,
  systemPromptTemplates,
  promptActive,
  isShortening,
}: ShortenDialogProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [combinedAvailability, setCombinedAvailability] = useState<Record<string, boolean> | null>(null)
  const [combinedAvailabilityLoading, setCombinedAvailabilityLoading] = useState(false)
  const [promptChoice, setPromptChoice] = useState<Partial<Record<PromptStage, string | "default">>>({
    summary: (promptActive?.summary as string | "default") || "default",
    shorten: (promptActive?.shorten as string | "default") || "default",
  })
  const [hasTouchedPromptChoice, setHasTouchedPromptChoice] = useState(false)
  const [localShortenLoading, setLocalShortenLoading] = useState(false)

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
      setCombinedAvailability(null)
      setCombinedAvailabilityLoading(false)
      return
    }

    const ids = sortedKapiteln.map((k) => k.id)
    if (ids.length === 0) {
      setCombinedAvailability({})
      return
    }

    let cancelled = false
    setCombinedAvailabilityLoading(true)

    getKapitelsWithCombinedText(ids)
      .then((result) => {
        if (cancelled) return
        setCombinedAvailability(result)
      })
      .catch((err) => {
        console.error("Failed to check Kapitel combined text availability", err)
        if (cancelled) return
        setCombinedAvailability({})
      })
      .finally(() => {
        if (cancelled) return
        setCombinedAvailabilityLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [open, sortedKapiteln])

  const hasCombinedText = (kapitelId: string) => {
    if (combinedAvailabilityLoading || !combinedAvailability) return false
    return Boolean(combinedAvailability[kapitelId])
  }

  const toggleKapitel = (id: string) => {
    if (!hasCombinedText(id)) return
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
      shorten: (promptActive?.shorten as string | "default") || "default",
    })
  }, [
    open,
    promptActive?.summary,
    promptActive?.shorten,
    hasTouchedPromptChoice,
  ])

  const handleShorten = async () => {
    if (selectedIds.length === 0 || localShortenLoading || isShortening) return
    setLocalShortenLoading(true)
    onOpenChange(false)
    try {
      await onShorten(selectedIds, promptChoice)
      setSelectedIds([])
    } finally {
      setLocalShortenLoading(false)
    }
  }

  const getIndentLevel = (nummer: string) => nummer.split(".").length - 1

  const showPromptSelectors = askOnEachProcess

  const renderPromptSelect = (stage: PromptStage, label: string) => {
    const options = promptTemplates.filter((p) => p.stage === stage)
    const systemOptions = systemPromptTemplates
      .filter((p) => p.stage === stage)
      .slice()
      .sort((a, b) => {
        const rank = (key: string) => (key === "default" ? 0 : key === "default_v2" ? 1 : 2)
        const ra = rank(a.templateKey)
        const rb = rank(b.templateKey)
        if (ra !== rb) return ra - rb
        return a.name.localeCompare(b.name, "de")
      })
    return (
      <div className="space-y-2">
        <Label className="text-sm">{label}</Label>
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
            {systemOptions.map((p) => (
              <SelectItem key={`sys-${p.templateKey}`} value={p.templateKey}>
                <span className="text-muted-foreground">{p.name}</span>
              </SelectItem>
            ))}
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
      <DialogContent className="sm:max-w-lg [&>button]:hidden">
        <DialogHeader className="pb-4 border-b">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Scissors className="h-4 w-4 text-primary" />
            </div>
            Text kürzen
          </DialogTitle>
          <DialogDescription className="pt-1">
            Wähle andere Kapitel als Kontext, um den Text konsistent zu kürzen
          </DialogDescription>
        </DialogHeader>

        <div className="py-4 max-h-[60vh] overflow-y-auto space-y-4">
          {showPromptSelectors && (
            <div className="pb-4 border-b space-y-4">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <MessageSquareText className="h-4 w-4" />
                Prompts
              </div>
              <div className="grid gap-4">
                {renderPromptSelect("summary", "Zusammenfassung")}
                {renderPromptSelect("shorten", "Kürzen")}
              </div>
            </div>
          )}

          <p className="text-sm text-muted-foreground">
            Wähle 5-8 Kapitel aus, deren Inhalte als Kontext für die Kürzung verwendet werden. Nur Kapitel mit
            kombiniertem Text können ausgewählt werden.
          </p>

          <div className="border rounded-lg max-h-[280px] overflow-y-auto">
            <TooltipProvider>
              {sortedKapiteln.map((kapitel) => {
                const hasCombined = hasCombinedText(kapitel.id)
                const isSelected = selectedIds.includes(kapitel.id)
                const indentLevel = getIndentLevel(kapitel.nummer)
                const availabilityKnown = !combinedAvailabilityLoading && combinedAvailability !== null

                return (
                  <Tooltip key={kapitel.id}>
                    <TooltipTrigger asChild>
                      <button
                        className={cn(
                          "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors border-b last:border-b-0",
                          hasCombined && "hover:bg-muted/50 cursor-pointer",
                          !hasCombined && "opacity-50 cursor-not-allowed",
                          isSelected && "bg-primary/10",
                        )}
                        onClick={() => toggleKapitel(kapitel.id)}
                        disabled={!hasCombined}
                        style={{ paddingLeft: `${16 + indentLevel * 20}px` }}
                      >
                        <div
                          className={cn(
                            "w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors",
                            isSelected
                              ? "bg-primary border-primary text-primary-foreground"
                              : hasCombined
                                ? "border-muted-foreground/30"
                                : "border-muted-foreground/20 bg-muted/30",
                          )}
                        >
                          {isSelected && <ChevronRight className="h-3 w-3" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <span className="text-sm">
                            <span className="text-muted-foreground mr-1.5">{kapitel.nummer}</span>
                            <span className={cn(!hasCombined && "text-muted-foreground")}>{kapitel.title}</span>
                          </span>
                        </div>
                        {!hasCombined && <AlertCircle className="h-4 w-4 text-muted-foreground/50 shrink-0" />}
                      </button>
                    </TooltipTrigger>
                    {!hasCombined && (
                      <TooltipContent side="left">
                        <p>
                          {!availabilityKnown
                            ? "Prüfe Text..."
                            : "Dieses Kapitel hat noch keinen kombinierten Text"}
                        </p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                )
              })}
            </TooltipProvider>
          </div>

          {selectedIds.length > 0 && (
            <p className="text-sm text-muted-foreground mt-1">{selectedIds.length} Kapitel ausgewählt</p>
          )}

          {/* Model is fixed per run; don't show it in the dialog. */}
        </div>

        <DialogFooter className="pt-4 border-t gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button
            onClick={handleShorten}
            disabled={selectedIds.length === 0 || localShortenLoading || isShortening}
          >
            {localShortenLoading || isShortening ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Scissors className="h-4 w-4 mr-2" />
            )}
            Text kürzen ({selectedIds.length} Kontext)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
