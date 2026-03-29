"use client"

import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { Plus, Trash2, MoreVertical, Pencil, Loader2, Check, FileText, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import type { Kapitel } from "@/app/types/ui"

type KapitelStage = 0 | 1 | 2 | 3 | 4

type KapitelIndicator = {
  stage: KapitelStage
  isProcessing: boolean
}

interface KapitelNavigatorProps {
  kapiteln: Kapitel[]
  kapitelIndicators: Record<string, KapitelIndicator>
  activeKapitelId: string
  onKapitelSelect: (id: string) => void
  onAddKapitel: (title: string, nummer: string, thema: string) => Promise<void>
  onDeleteKapitel: (id: string, name: string) => void
  onEditKapitel: (id: string, title: string, nummer: string, thema: string) => Promise<void>
  addKapitelLoading: boolean
  editKapitelLoading: boolean
  gliederungMode?: "empty" | "review"
  onOpenGliederungCreate?: () => void
  openAddDialogSignal?: number
}

function KapitelStageIndicator({ stage, isProcessing }: KapitelIndicator) {
  if (isProcessing) {
    return <Loader2 className="h-4 w-4 mt-0.5 shrink-0 animate-spin text-orange-500" />
  }

  if (stage === 4) {
    return (
      <div
        className="mt-0.5 shrink-0 h-4 w-4 rounded-full bg-primary text-primary-foreground flex items-center justify-center"
        aria-label="Verbessert"
        title="Verbessert"
      >
        <Check className="h-3 w-3" />
      </div>
    )
  }

  const progress = stage / 4
  const radius = 6
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - progress)

  const label =
    stage === 3 ? "Gekürzt" : stage === 2 ? "Kombiniert" : stage === 1 ? "Quellen" : "Noch nicht verarbeitet"

  return (
    <div className="relative h-4 w-4 mt-0.5 shrink-0" aria-label={label}>
      <svg width="16" height="16" viewBox="0 0 16 16" className="h-4 w-4">
        <title>{label}</title>
        <circle
          cx="8"
          cy="8"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-muted-foreground/30"
        />
        <circle
          cx="8"
          cy="8"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform="rotate(-90 8 8)"
          className={cn(stage > 0 ? "text-primary" : "text-transparent")}
        />
      </svg>
    </div>
  )
}

function getIndentLevel(nummer: string): number {
  const parts = nummer.split(".")
  return parts.length - 1
}

function isValidNummer(nummer: string): boolean {
  const regex = /^\d+(\.\d+)?(\.\d+)?$/
  return regex.test(nummer) && nummer.split(".").length <= 3
}

function sortByNummer(a: Kapitel, b: Kapitel): number {
  const partsA = a.nummer.split(".").map(Number)
  const partsB = b.nummer.split(".").map(Number)

  for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
    const numA = partsA[i] ?? 0
    const numB = partsB[i] ?? 0
    if (numA !== numB) return numA - numB
  }
  return 0
}

export function KapitelNavigator({
  kapiteln,
  kapitelIndicators,
  activeKapitelId,
  onKapitelSelect,
  onAddKapitel,
  onDeleteKapitel,
  onEditKapitel,
  addKapitelLoading,
  editKapitelLoading,
  gliederungMode,
  onOpenGliederungCreate,
  openAddDialogSignal,
}: KapitelNavigatorProps) {
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingKapitel, setEditingKapitel] = useState<Kapitel | null>(null)
  const [newKapitelTitle, setNewKapitelTitle] = useState("")
  const [newKapitelNummer, setNewKapitelNummer] = useState("")
  const [newKapitelThema, setNewKapitelThema] = useState("")
  const [nummerError, setNummerError] = useState("")
  const [localAddLoading, setLocalAddLoading] = useState(false)
  const [localEditLoading, setLocalEditLoading] = useState(false)

  const prevOpenAddSignalRef = useRef(openAddDialogSignal ?? 0)
  useEffect(() => {
    const next = openAddDialogSignal ?? 0
    const prev = prevOpenAddSignalRef.current
    if (!next || next === prev) return
    prevOpenAddSignalRef.current = next
    setAddDialogOpen(true)
  }, [openAddDialogSignal])

  const sortedKapiteln = [...kapiteln].sort(sortByNummer)

  const handleAddKapitel = async () => {
    if (!newKapitelTitle.trim() || !newKapitelNummer.trim() || localAddLoading || addKapitelLoading) return

    if (!isValidNummer(newKapitelNummer.trim())) {
      setNummerError("Bitte gib eine gültige Nummer ein (z.B. 1, 1.1 oder 1.1.1)")
      return
    }

    setLocalAddLoading(true)
    setAddDialogOpen(false)
    try {
      await onAddKapitel(newKapitelTitle.trim(), newKapitelNummer.trim(), newKapitelThema.trim())
      setNewKapitelTitle("")
      setNewKapitelNummer("")
      setNewKapitelThema("")
      setNummerError("")
    } finally {
      setLocalAddLoading(false)
    }
  }

  const handleEditKapitel = async () => {
    if (!editingKapitel || !newKapitelTitle.trim() || !newKapitelNummer.trim() || localEditLoading || editKapitelLoading) return

    if (!isValidNummer(newKapitelNummer.trim())) {
      setNummerError("Bitte gib eine gültige Nummer ein (z.B. 1, 1.1 oder 1.1.1)")
      return
    }

    setLocalEditLoading(true)
    setEditDialogOpen(false)
    try {
      await onEditKapitel(editingKapitel.id, newKapitelTitle.trim(), newKapitelNummer.trim(), newKapitelThema.trim())
      setEditingKapitel(null)
      setNewKapitelTitle("")
      setNewKapitelNummer("")
      setNewKapitelThema("")
      setNummerError("")
    } finally {
      setLocalEditLoading(false)
    }
  }

  const openEditDialog = (kapitel: Kapitel) => {
    setEditingKapitel(kapitel)
    setNewKapitelTitle(kapitel.title)
    setNewKapitelNummer(kapitel.nummer)
    setNewKapitelThema(kapitel.thema || "")
    setNummerError("")
    setEditDialogOpen(true)
  }

  return (
    <>
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {sortedKapiteln.length === 0 && gliederungMode ? (
          <div className="px-2 pt-4 pb-6">
            {gliederungMode === "empty" ? (
              <div className="flex flex-col items-center text-center gap-3">
                <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center">
                  <FileText className="h-5 w-5 text-muted-foreground" />
                </div>
                <div className="text-sm font-medium text-foreground">Noch keine Kapitel vorhanden</div>
                <Button
                  variant="outline"
                  className="h-9"
                  onClick={() => onOpenGliederungCreate?.()}
                  disabled={!onOpenGliederungCreate}
                >
                  <Sparkles className="h-4 w-4 mr-2" />
                  Gliederung erstellen
                </Button>
              </div>
            ) : (
              <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-left">
                <div className="flex items-start gap-2">
                  <Sparkles className="h-4 w-4 text-primary mt-0.5" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground">Gliederung wird überprüft</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      Bestätige die Gliederung um fortzufahren.
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : null}

        <div className="space-y-0.5">
          {sortedKapiteln.map((kapitel) => {
            const isActive = kapitel.id === activeKapitelId
            const indentLevel = getIndentLevel(kapitel.nummer)
            const indicator = kapitelIndicators[kapitel.id] ?? { stage: 0, isProcessing: false }

            return (
              <div
                key={kapitel.id}
                className={cn(
                  "group flex items-center gap-1 rounded-md transition-colors",
                  isActive && "bg-sidebar-accent",
                )}
              >
                <button
                  onClick={() => onKapitelSelect(kapitel.id)}
                  className={cn(
                    "flex-1 text-left py-2.5 text-sm",
                    isActive && "border-l-2 border-primary",
                    indentLevel === 0 && "pl-3",
                    indentLevel === 1 && "pl-7",
                    indentLevel === 2 && "pl-11",
                  )}
                >
                  <div className="flex items-start gap-2">
                    <KapitelStageIndicator stage={indicator.stage} isProcessing={indicator.isProcessing} />
                    <div className="flex-1 min-w-0">
                      <div
                        className={cn(
                          "leading-snug",
                          isActive ? "text-sidebar-foreground font-medium" : "text-sidebar-foreground/70",
                        )}
                      >
                        <span className="text-muted-foreground/60 mr-1.5">{kapitel.nummer}</span>
                        {kapitel.title}
                      </div>
                    </div>
                  </div>
                </button>

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 opacity-40 hover:opacity-100 group-hover:opacity-100 transition-opacity"
                    >
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => openEditDialog(kapitel)}>
                      <Pencil className="mr-2 h-4 w-4" />
                      Bearbeiten
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => onDeleteKapitel(kapitel.id, kapitel.title)}
                      className="text-destructive focus:text-destructive"
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      Löschen
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            )
          })}
        </div>
      </nav>

      {/* Add Kapitel Button */}
      <div className="p-3 border-t border-sidebar-border">
        <Button
          variant="outline"
          className="w-full justify-start text-muted-foreground bg-transparent"
          onClick={() => setAddDialogOpen(true)}
        >
          <Plus className="mr-2 h-4 w-4" />
          Neues Kapitel
        </Button>
      </div>

      {/* Add Dialog */}
      <Dialog
        open={addDialogOpen}
        onOpenChange={(open) => {
          setAddDialogOpen(open)
          if (!open) {
            setNummerError("")
            setNewKapitelTitle("")
            setNewKapitelNummer("")
            setNewKapitelThema("")
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Neues Kapitel erstellen</DialogTitle>
          </DialogHeader>
          <div className="py-4 space-y-4">
            <div>
              <Label htmlFor="kapitel-nummer" className="text-sm text-muted-foreground">
                Kapitelnummer
              </Label>
              <Input
                id="kapitel-nummer"
                value={newKapitelNummer}
                onChange={(e) => {
                  setNewKapitelNummer(e.target.value)
                  setNummerError("")
                }}
                placeholder="z.B. 1, 1.1 oder 1.1.1"
                className={cn("mt-2", nummerError && "border-destructive")}
              />
              {nummerError && <p className="text-xs text-destructive mt-1">{nummerError}</p>}
              <p className="text-xs text-muted-foreground mt-1">Maximal 3 Ebenen (z.B. 2.3.1)</p>
            </div>
            <div>
              <Label htmlFor="kapitel-title" className="text-sm text-muted-foreground">
                Kapitelüberschrift
              </Label>
              <Input
                id="kapitel-title"
                value={newKapitelTitle}
                onChange={(e) => setNewKapitelTitle(e.target.value)}
                placeholder="z.B. Theoretischer Rahmen"
                className="mt-2"
                onKeyDown={(e) => e.key === "Enter" && handleAddKapitel()}
              />
            </div>
            <div>
              <Label htmlFor="kapitel-thema" className="text-sm text-muted-foreground">
                Thema & Anweisungen (Standard)
              </Label>
              <Textarea
                id="kapitel-thema"
                value={newKapitelThema}
                onChange={(e) => setNewKapitelThema(e.target.value)}
                placeholder="Beschreibe, worum es in diesem Kapitel gehen soll und gib spezifische Anweisungen..."
                className="mt-2 min-h-[90px] resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button
              onClick={handleAddKapitel}
              disabled={
                !newKapitelTitle.trim() ||
                !newKapitelNummer.trim() ||
                localAddLoading ||
                addKapitelLoading
              }
            >
              {localAddLoading || addKapitelLoading ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : null}
              Erstellen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog
        open={editDialogOpen}
        onOpenChange={(open) => {
          setEditDialogOpen(open)
          if (!open) {
            setNummerError("")
            setEditingKapitel(null)
            setNewKapitelTitle("")
            setNewKapitelNummer("")
            setNewKapitelThema("")
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Kapitel bearbeiten</DialogTitle>
          </DialogHeader>
          <div className="py-4 space-y-4">
            <div>
              <Label htmlFor="edit-kapitel-nummer" className="text-sm text-muted-foreground">
                Kapitelnummer
              </Label>
              <Input
                id="edit-kapitel-nummer"
                value={newKapitelNummer}
                onChange={(e) => {
                  setNewKapitelNummer(e.target.value)
                  setNummerError("")
                }}
                placeholder="z.B. 1, 1.1 oder 1.1.1"
                className={cn("mt-2", nummerError && "border-destructive")}
              />
              {nummerError && <p className="text-xs text-destructive mt-1">{nummerError}</p>}
              <p className="text-xs text-muted-foreground mt-1">Maximal 3 Ebenen (z.B. 2.3.1)</p>
            </div>
            <div>
              <Label htmlFor="edit-kapitel-title" className="text-sm text-muted-foreground">
                Kapitelüberschrift
              </Label>
              <Input
                id="edit-kapitel-title"
                value={newKapitelTitle}
                onChange={(e) => setNewKapitelTitle(e.target.value)}
                placeholder="z.B. Theoretischer Rahmen"
                className="mt-2"
                onKeyDown={(e) => e.key === "Enter" && handleEditKapitel()}
              />
            </div>
            <div>
              <Label htmlFor="edit-kapitel-thema" className="text-sm text-muted-foreground">
                Thema & Anweisungen (Standard)
              </Label>
              <Textarea
                id="edit-kapitel-thema"
                value={newKapitelThema}
                onChange={(e) => setNewKapitelThema(e.target.value)}
                placeholder="Beschreibe, worum es in diesem Kapitel gehen soll und gib spezifische Anweisungen..."
                className="mt-2 min-h-[90px] resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button
              onClick={handleEditKapitel}
              disabled={
                !newKapitelTitle.trim() ||
                !newKapitelNummer.trim() ||
                localEditLoading ||
                editKapitelLoading
              }
            >
              {localEditLoading || editKapitelLoading ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : null}
              Speichern
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
