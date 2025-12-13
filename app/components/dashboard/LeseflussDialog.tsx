"use client"

import { useMemo, useState } from "react"
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
import { Sparkles, AlertCircle, MessageSquareText } from "lucide-react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import type { Kapitel } from "@/app/types/ui"
import type { ActivePromptSelections, PromptStage, PromptTemplate } from "@/app/types/prompts"

interface LeseflussDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  allKapitels: Kapitel[]
  currentKapitelId: string
  onLesefluss: (
    contextKapitelIds: string[],
    aufgabenstellung: string,
    model: string,
    promptChoice?: Record<PromptStage, string | "default">
  ) => void
  askOnEachProcess: boolean
  promptTemplates: PromptTemplate[]
  promptActive: ActivePromptSelections
}

export function LeseflussDialog({
  open,
  onOpenChange,
  allKapitels,
  currentKapitelId,
  onLesefluss,
  askOnEachProcess,
  promptTemplates,
  promptActive,
}: LeseflussDialogProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [aufgabenstellung, setAufgabenstellung] = useState("")
  const [model, setModel] = useState<"gpt-5-nano" | "gpt-5-mini" | "gpt-5.2">("gpt-5-mini")
  const [promptChoice, setPromptChoice] = useState<Record<PromptStage, string | "default">>({
    summary: (promptActive?.summary as string | "default") || "default",
    lesefluss: (promptActive?.lesefluss as string | "default") || "default",
  })

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

  const hasCombinedText = (kapitelId: string) => {
    const target = allKapitels.find((k) => k.id === kapitelId)
    return target?.status === "fertig"
  }

  const toggleKapitel = (id: string) => {
    if (!hasCombinedText(id)) return
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]))
  }

  const handleSubmit = () => {
    if (selectedIds.length === 0 || aufgabenstellung.trim().length < 10) return
    onLesefluss(selectedIds, aufgabenstellung.trim(), model, promptChoice)
    setSelectedIds([])
    setAufgabenstellung("")
  }

  const getIndentLevel = (nummer: string) => nummer.split(".").length - 1
  const showPromptSelectors = askOnEachProcess && promptTemplates.length > 0

  const renderPromptSelect = (stage: PromptStage, label: string) => {
    const options = promptTemplates.filter((p) => p.stage === stage)
    if (options.length === 0) return null
    return (
      <div className="space-y-2">
        <Label className="text-sm">Prompt für {label}</Label>
        <Select
          value={promptChoice[stage] || "default"}
          onValueChange={(val) =>
            setPromptChoice((prev) => ({
              ...prev,
              [stage]: val as string | "default",
            }))
          }
        >
          <SelectTrigger className="mt-1.5">
            <SelectValue placeholder="System-Standard" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="default">
              <span className="text-muted-foreground">System-Standard</span>
            </SelectItem>
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
              Wähle andere Kapitel aus, die als Kontext verwendet werden sollen. Nur Kapitel mit kombiniertem Text können ausgewählt werden.
            </p>
            <div className="border rounded-lg max-h-[240px] overflow-y-auto">
              <TooltipProvider>
                {sortedKapiteln.map((kapitel) => {
                  const hasCombined = hasCombinedText(kapitel.id)
                  const isSelected = selectedIds.includes(kapitel.id)
                  const indentLevel = getIndentLevel(kapitel.nummer)

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
                          <p>Dieses Kapitel hat noch keinen kombinierten Text</p>
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

          <div className="space-y-2">
            <Label htmlFor="lesefluss-model">Modell</Label>
            <Select value={model} onValueChange={(value) => setModel(value as typeof model)}>
              <SelectTrigger id="lesefluss-model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="gpt-5-nano">gpt-5-nano (Empfohlen)</SelectItem>
                <SelectItem value="gpt-5-mini">gpt-5-mini (Beste Qualität)</SelectItem>
                <SelectItem value="gpt-5.2">gpt-5.2 (Beste Qualität)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter className="pt-4 border-t gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={selectedIds.length === 0 || aufgabenstellung.trim().length < 10}
          >
            <Sparkles className="h-4 w-4 mr-2" />
            Lesefluss verbessern ({selectedIds.length} Kontext)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
