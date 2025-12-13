"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Circle, CheckCircle2, Clock, Plus, Trash2, MoreVertical, Pencil, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { Kapitel } from "@/app/types/ui"

interface KapitelNavigatorProps {
  kapiteln: Kapitel[]
  activeKapitelId: string
  onKapitelSelect: (id: string) => void
  onAddKapitel: (title: string, nummer: string) => Promise<void>
  onDeleteKapitel: (id: string, name: string) => void
  onEditKapitel: (id: string, title: string, nummer: string) => Promise<void>
  addKapitelLoading: boolean
  editKapitelLoading: boolean
}

const statusConfig = {
  "nicht-verarbeitet": {
    icon: Circle,
    color: "text-muted-foreground/40",
    label: "Noch nicht verarbeitet",
  },
  "in-bearbeitung": {
    icon: Clock,
    color: "text-amber-500",
    label: "In Bearbeitung",
  },
  fertig: {
    icon: CheckCircle2,
    color: "text-primary",
    label: "Fertig",
  },
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
  activeKapitelId,
  onKapitelSelect,
  onAddKapitel,
  onDeleteKapitel,
  onEditKapitel,
  addKapitelLoading,
  editKapitelLoading,
}: KapitelNavigatorProps) {
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingKapitel, setEditingKapitel] = useState<Kapitel | null>(null)
  const [newKapitelTitle, setNewKapitelTitle] = useState("")
  const [newKapitelNummer, setNewKapitelNummer] = useState("")
  const [nummerError, setNummerError] = useState("")
  const [localAddLoading, setLocalAddLoading] = useState(false)
  const [localEditLoading, setLocalEditLoading] = useState(false)

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
      await onAddKapitel(newKapitelTitle.trim(), newKapitelNummer.trim())
      setNewKapitelTitle("")
      setNewKapitelNummer("")
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
      await onEditKapitel(editingKapitel.id, newKapitelTitle.trim(), newKapitelNummer.trim())
      setEditingKapitel(null)
      setNewKapitelTitle("")
      setNewKapitelNummer("")
      setNummerError("")
    } finally {
      setLocalEditLoading(false)
    }
  }

  const openEditDialog = (kapitel: Kapitel) => {
    setEditingKapitel(kapitel)
    setNewKapitelTitle(kapitel.title)
    setNewKapitelNummer(kapitel.nummer)
    setNummerError("")
    setEditDialogOpen(true)
  }

  return (
    <>
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <div className="space-y-0.5">
          {sortedKapiteln.map((kapitel) => {
            const isActive = kapitel.id === activeKapitelId
            const StatusIcon = statusConfig[kapitel.status].icon
            const statusColor = statusConfig[kapitel.status].color
            const indentLevel = getIndentLevel(kapitel.nummer)

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
                    <StatusIcon className={cn("h-4 w-4 mt-0.5 shrink-0", statusColor)} />
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
                      className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
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
