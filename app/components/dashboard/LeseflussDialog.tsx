"use client"

import { useState, useMemo } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Sparkles, Info, Settings2, FileText } from "lucide-react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { Kapitel, Run } from "@/app/types/ui"

interface LeseflussDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kapitel: Kapitel
  selectedRun: Run | undefined
  allKapitels: Kapitel[]
  onLesefluss: (contextKapitelIds: string[], aufgabenstellung: string, model: string) => void
}

export function LeseflussDialog({
  open,
  onOpenChange,
  kapitel,
  selectedRun,
  allKapitels,
  onLesefluss,
}: LeseflussDialogProps) {
  const [selectedKapitelIds, setSelectedKapitelIds] = useState<Set<string>>(new Set())
  const [aufgabenstellung, setAufgabenstellung] = useState("")
  const [model, setModel] = useState<"gpt-5-nano" | "gpt-5-mini" | "gpt-5.2">("gpt-5-nano")

  // Build kapitel tree
  const kapitelTree = useMemo(() => buildKapitelTree(allKapitels, kapitel.id), [allKapitels, kapitel.id])

  // Check if a kapitel has shortened text
  const hasShortenedText = (kapitelToCheck: Kapitel): boolean => {
    // In real app, would need to check actual runs data
    // For now, simple heuristic: if it has status "fertig", assume it might have shortened text
    // This should be enhanced to actually check for shortened results
    return kapitelToCheck.status === "fertig"
  }

  const handleKapitelToggle = (kapitelId: string) => {
    setSelectedKapitelIds((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(kapitelId)) {
        newSet.delete(kapitelId)
      } else {
        newSet.add(kapitelId)
      }
      return newSet
    })
  }

  const handleSubmit = () => {
    if (selectedKapitelIds.size === 0) return
    if (aufgabenstellung.trim().length < 10) return

    onLesefluss(Array.from(selectedKapitelIds), aufgabenstellung.trim(), model)
    onOpenChange(false)

    // Reset form
    setSelectedKapitelIds(new Set())
    setAufgabenstellung("")
    setModel("gpt-5-nano")
  }

  const renderKapitelTree = (tree: KapitelTreeNode[], depth: number = 0) => {
    return tree.map((node) => {
      const isSelectable = hasShortenedText(node.kapitel)
      const isSelected = selectedKapitelIds.has(node.kapitel.id)

      return (
        <div key={node.kapitel.id} className="space-y-2">
          <div className="flex items-center gap-2" style={{ paddingLeft: `${depth * 20}px` }}>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id={`kapitel-${node.kapitel.id}`}
                      checked={isSelected}
                      onCheckedChange={() => handleKapitelToggle(node.kapitel.id)}
                      disabled={!isSelectable}
                    />
                    <Label
                      htmlFor={`kapitel-${node.kapitel.id}`}
                      className={`cursor-pointer ${!isSelectable ? "text-muted-foreground" : ""}`}
                    >
                      <span className="text-muted-foreground mr-2">{node.kapitel.nummer}</span>
                      {node.kapitel.title}
                    </Label>
                  </div>
                </TooltipTrigger>
                {!isSelectable && (
                  <TooltipContent>
                    <p>Kein gekürzter Text vorhanden</p>
                  </TooltipContent>
                )}
              </Tooltip>
            </TooltipProvider>
          </div>
          {node.children.length > 0 && renderKapitelTree(node.children, depth + 1)}
        </div>
      )
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] flex flex-col [&>button]:hidden">
        <DialogHeader className="pb-4 border-b">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            Lesefluss verbessern
          </DialogTitle>
          <DialogDescription className="pt-1">
            {kapitel.nummer} {kapitel.title}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-5 overflow-y-auto flex-1">
          {/* Aufgabenstellung Input */}
          <div className="space-y-2">
            <Label htmlFor="aufgabenstellung" className="flex items-center gap-2">
              Aufgabenstellung für die gesamte Arbeit
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <Info className="h-4 w-4 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p>
                      Beschreibe die Aufgabenstellung bzw. das Ziel deiner wissenschaftlichen Arbeit.
                      Dies gibt dem Modell Kontext für die Verbesserung des Leseflusses.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </Label>
            <Textarea
              id="aufgabenstellung"
              placeholder="z.B. Analyse der Auswirkungen von KI auf die Arbeitswelt..."
              value={aufgabenstellung}
              onChange={(e) => setAufgabenstellung(e.target.value)}
              rows={6}
              className="resize-none"
            />
            <p className="text-xs text-muted-foreground">
              Mindestens 10 Zeichen erforderlich ({aufgabenstellung.length} / 10)
            </p>
          </div>

          {/* Context Kapitel Selection */}
          <div className="space-y-2">
            <Label>Kontext-Kapitel auswählen</Label>
            <p className="text-sm text-muted-foreground">
              Wähle andere Kapitel aus, die als Kontext verwendet werden sollen.
            </p>
            <div className="border rounded-lg p-4 max-h-[300px] overflow-y-auto space-y-2">
              {kapitelTree.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  Keine Kapitel verfügbar
                </p>
              ) : (
                renderKapitelTree(kapitelTree)
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {selectedKapitelIds.size} Kapitel ausgewählt
            </p>
          </div>

          {/* Current Kapitel Info */}
          {selectedRun && (
            <div className="space-y-2 p-4 bg-muted/30 rounded-lg">
              <div className="text-sm">
                <span className="font-medium">Aktuelles Kapitel: </span>
                <span className="text-muted-foreground">{kapitel.nummer} {kapitel.title}</span>
              </div>
              <div className="text-sm">
                <span className="font-medium">Überschrift: </span>
                <span className="text-muted-foreground">{selectedRun.ueberschrift}</span>
              </div>
              <div className="text-sm">
                <span className="font-medium">Thema: </span>
                <span className="text-muted-foreground">{selectedRun.thema}</span>
              </div>
            </div>
          )}

          {/* Model Selection */}
          <div className="space-y-2">
            <Label htmlFor="model">Modell</Label>
            <Select value={model} onValueChange={(value: any) => setModel(value)}>
              <SelectTrigger id="model">
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
            disabled={selectedKapitelIds.size === 0 || aufgabenstellung.trim().length < 10}
          >
            <Sparkles className="h-4 w-4 mr-2" />
            Lesefluss verbessern
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Helper types and functions (same as ShortenDialog)
type KapitelTreeNode = {
  kapitel: Kapitel
  children: KapitelTreeNode[]
}

function buildKapitelTree(allKapitels: Kapitel[], excludeId: string): KapitelTreeNode[] {
  const filtered = allKapitels.filter((k) => k.id !== excludeId)

  const map = new Map<string, KapitelTreeNode>()
  filtered.forEach((k) => {
    map.set(k.id, { kapitel: k, children: [] })
  })

  const roots: KapitelTreeNode[] = []

  filtered.forEach((k) => {
    const node = map.get(k.id)!
    if (k.parentId && map.has(k.parentId)) {
      map.get(k.parentId)!.children.push(node)
    } else {
      roots.push(node)
    }
  })

  const sortByNummer = (nodes: KapitelTreeNode[]) => {
    nodes.sort((a, b) => {
      const numA = a.kapitel.nummer || ""
      const numB = b.kapitel.nummer || ""
      return numA.localeCompare(numB, undefined, { numeric: true })
    })
    nodes.forEach((n) => sortByNummer(n.children))
  }

  sortByNummer(roots)

  return roots
}
