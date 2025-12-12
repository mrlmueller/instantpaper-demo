"use client"

import { useState, useMemo } from "react"
import { Scissors, Settings2, FileText, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { Kapitel, Run } from "@/app/types/ui"

interface ShortenDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kapitel: Kapitel
  selectedRun: Run | undefined
  allKapitels: Kapitel[]
  onShorten: (contextKapitelIds: string[], model: string) => void
}

// Helper to build hierarchical tree structure
interface TreeNode {
  kapitel: Kapitel
  children: TreeNode[]
}

function buildKapitelTree(kapitels: Kapitel[], targetKapitelId: string): TreeNode[] {
  // Filter out the target Kapitel
  const filteredKapitels = kapitels.filter((k) => k.id !== targetKapitelId)

  // Create a map of id -> node
  const nodeMap = new Map<string, TreeNode>()
  filteredKapitels.forEach((k) => {
    nodeMap.set(k.id, { kapitel: k, children: [] })
  })

  // Build tree structure
  const roots: TreeNode[] = []

  filteredKapitels.forEach((k) => {
    const node = nodeMap.get(k.id)!
    if (!k.parentId) {
      // Top-level Kapitel
      roots.push(node)
    } else {
      // Child Kapitel
      const parent = nodeMap.get(k.parentId)
      if (parent) {
        parent.children.push(node)
      } else {
        // Parent not found, treat as root
        roots.push(node)
      }
    }
  })

  // Sort roots and children by nummer
  const sortByNummer = (a: TreeNode, b: TreeNode) => {
    const numA = a.kapitel.nummer || ""
    const numB = b.kapitel.nummer || ""
    return numA.localeCompare(numB, undefined, { numeric: true })
  }

  const sortRecursive = (nodes: TreeNode[]) => {
    nodes.sort(sortByNummer)
    nodes.forEach((node) => sortRecursive(node.children))
  }

  sortRecursive(roots)

  return roots
}

export function ShortenDialog({
  open,
  onOpenChange,
  kapitel,
  selectedRun,
  allKapitels,
  onShorten,
}: ShortenDialogProps) {
  const [selectedKapitelIds, setSelectedKapitelIds] = useState<Set<string>>(new Set())
  const [model, setModel] = useState<"gpt-5-nano" | "gpt-5-mini" | "gpt-5.2">("gpt-5-nano")

  const kapitelTree = useMemo(() => buildKapitelTree(allKapitels, kapitel.id), [allKapitels, kapitel.id])

  const handleToggleKapitel = (kapitelId: string) => {
    setSelectedKapitelIds((prev) => {
      const next = new Set(prev)
      if (next.has(kapitelId)) {
        next.delete(kapitelId)
      } else {
        next.add(kapitelId)
      }
      return next
    })
  }

  // Check if a Kapitel is selectable (has combined text OR has exactly 1 Quelle)
  const isKapitelSelectable = (kapitelToCheck: Kapitel): boolean => {
    // Has combined text (status "fertig")
    if (kapitelToCheck.status === "fertig") {
      return true
    }
    // Has exactly 1 assigned Quelle
    if (kapitelToCheck.assignedQuellenIds.length === 1) {
      return true
    }
    return false
  }

  const handleShorten = () => {
    if (selectedKapitelIds.size === 0) {
      return
    }

    onShorten(Array.from(selectedKapitelIds), model)
    onOpenChange(false)
  }

  const handleOpenChange = (open: boolean) => {
    if (open) {
      // Reset state when opening
      setSelectedKapitelIds(new Set())
      setModel("gpt-5-nano")
    }
    onOpenChange(open)
  }

  // Render tree node recursively
  const renderTreeNode = (node: TreeNode, depth: number = 0) => {
    const indentClass = depth > 0 ? `pl-${depth * 6}` : ""
    const hasChildren = node.children.length > 0
    const isSelectable = isKapitelSelectable(node.kapitel)

    const checkboxElement = (
      <div className={`flex items-center py-2 ${indentClass}`}>
        <Checkbox
          id={node.kapitel.id}
          checked={selectedKapitelIds.has(node.kapitel.id)}
          onCheckedChange={() => handleToggleKapitel(node.kapitel.id)}
          disabled={!isSelectable}
          className="mr-3"
        />
        <label
          htmlFor={node.kapitel.id}
          className={`flex-1 text-sm select-none ${
            isSelectable ? "cursor-pointer" : "cursor-not-allowed opacity-50"
          }`}
        >
          <span className="text-muted-foreground mr-2">{node.kapitel.nummer}</span>
          <span>{node.kapitel.title}</span>
        </label>
      </div>
    )

    return (
      <div key={node.kapitel.id}>
        {isSelectable ? (
          checkboxElement
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              {checkboxElement}
            </TooltipTrigger>
            <TooltipContent>
              <p>Kein kombinierter Text generiert</p>
            </TooltipContent>
          </Tooltip>
        )}
        {hasChildren && node.children.map((child) => renderTreeNode(child, depth + 1))}
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-2xl [&>button]:hidden max-h-[90vh] flex flex-col">
        <DialogHeader className="pb-4 border-b">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Scissors className="h-4 w-4 text-primary" />
            </div>
            Text kürzen & Duplikate entfernen
          </DialogTitle>
          <DialogDescription className="pt-1">
            {kapitel.nummer} {kapitel.title}
          </DialogDescription>
        </DialogHeader>

        <div className="py-5 space-y-6 overflow-y-auto flex-1">
          {/* Section 1: Metadata Display */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <FileText className="h-4 w-4" />
              Aktuelle Informationen
            </div>

            <div className="grid gap-3 pl-6">
              <div>
                <Label className="text-xs text-muted-foreground">Überschrift</Label>
                <div className="mt-1 text-sm">{selectedRun?.ueberschrift || "N/A"}</div>
              </div>

              <div>
                <Label className="text-xs text-muted-foreground">Thema</Label>
                <div className="mt-1 text-sm line-clamp-2">{selectedRun?.thema || "N/A"}</div>
              </div>
            </div>
          </div>

          {/* Section 2: Kapitel Selection */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Sparkles className="h-4 w-4" />
              Kontext-Kapitel auswählen
            </div>

            <div className="pl-6">
              <Label className="text-sm mb-3 block">
                Wählen Sie die Kapitel, die als Kontext verwendet werden sollen
              </Label>

              <div className="border rounded-lg p-4 max-h-[300px] overflow-y-auto bg-muted/20">
                {kapitelTree.length === 0 ? (
                  <div className="text-sm text-muted-foreground text-center py-4">
                    Keine anderen Kapitel verfügbar
                  </div>
                ) : (
                  <TooltipProvider>
                    {kapitelTree.map((node) => renderTreeNode(node))}
                  </TooltipProvider>
                )}
              </div>

              <div className="mt-2 text-xs text-muted-foreground">
                {selectedKapitelIds.size} Kapitel ausgewählt
              </div>
            </div>
          </div>

          {/* Section 3: Model Selection */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Settings2 className="h-4 w-4" />
              Modelleinstellungen
            </div>

            <div className="pl-6">
              <Label htmlFor="model" className="text-sm">
                KI-Modell
              </Label>
              <Select
                value={model}
                onValueChange={(value) => setModel(value as typeof model)}
              >
                <SelectTrigger className="mt-1.5">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gpt-5-nano">
                    <div className="flex items-center justify-between w-full gap-4">
                      <span>GPT-5 nano</span>
                      <span className="text-xs text-muted-foreground">Empfohlen</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="gpt-5-mini">
                    <div className="flex items-center justify-between w-full gap-4">
                      <span>GPT-5 mini</span>
                      <span className="text-xs text-muted-foreground">Beste Qualität</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="gpt-5.2">
                    <div className="flex items-center justify-between w-full gap-4">
                      <span>GPT-5.2</span>
                      <span className="text-xs text-muted-foreground">Beste Qualität</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <DialogFooter className="pt-4 border-t gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button onClick={handleShorten} disabled={selectedKapitelIds.size === 0}>
            <Scissors className="h-4 w-4 mr-2" />
            Text kürzen
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
