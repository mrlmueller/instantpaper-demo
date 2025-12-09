"use client"

import { useState } from "react"
import { X, Plus, Trash2, Check, Eye, BookOpen, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import type { Quelle } from "@/app/types/ui"

interface QuellenPanelProps {
  quellen: Quelle[]
  assignedQuellenIds: string[]
  onClose: () => void
  onAddQuelle: (name: string, text: string) => Promise<void>
  onDeleteQuelle: (id: string, name: string) => void
  onAssignQuelle: (id: string) => Promise<void>
  onUnassignQuelle: (id: string) => Promise<void>
  onViewQuelle: (quelle: Quelle) => void
}

export function QuellenPanel({
  quellen,
  assignedQuellenIds,
  onClose,
  onAddQuelle,
  onDeleteQuelle,
  onAssignQuelle,
  onUnassignQuelle,
  onViewQuelle,
}: QuellenPanelProps) {
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [newQuelleName, setNewQuelleName] = useState("")
  const [newQuelleText, setNewQuelleText] = useState("")
  const [searchQuery, setSearchQuery] = useState("")

  const handleAddQuelle = async () => {
    if (newQuelleName.trim() && newQuelleText.trim()) {
      await onAddQuelle(newQuelleName.trim(), newQuelleText.trim())
      setNewQuelleName("")
      setNewQuelleText("")
      setAddDialogOpen(false)
    }
  }

  // Search functionality - filters by source name (client-side)
  const filteredQuellen = quellen.filter((q) => q.name.toLowerCase().includes(searchQuery.toLowerCase()))

  const assignedQuellen = filteredQuellen.filter((q) => assignedQuellenIds.includes(q.id))
  const unassignedQuellen = filteredQuellen.filter((q) => !assignedQuellenIds.includes(q.id))

  return (
    <>
      <div className="w-96 border-l border-border bg-background flex flex-col h-full">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-muted-foreground" />
            <h2 className="font-medium">Quellen</h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Search Bar */}
        <div className="px-4 pt-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Quellen durchsuchen..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="assigned" className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="mx-4 mt-4 grid grid-cols-2">
            <TabsTrigger value="assigned">Zugewiesen ({assignedQuellen.length})</TabsTrigger>
            <TabsTrigger value="all">Alle ({filteredQuellen.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="assigned" className="flex-1 overflow-y-auto p-4 space-y-3 mt-0">
            {assignedQuellen.length === 0 ? (
              <div className="text-center py-8 text-sm text-muted-foreground">
                {searchQuery ? (
                  <p>Keine zugewiesenen Quellen gefunden.</p>
                ) : (
                  <>
                    <p>Keine Quellen zugewiesen.</p>
                    <p className="mt-1">Wechsle zu "Alle", um Quellen hinzuzufügen.</p>
                  </>
                )}
              </div>
            ) : (
              assignedQuellen.map((quelle) => (
                <QuelleCard
                  key={quelle.id}
                  quelle={quelle}
                  isAssigned={true}
                  onToggleAssign={() => onUnassignQuelle(quelle.id)}
                  onDelete={() => onDeleteQuelle(quelle.id, quelle.name)}
                  onView={() => onViewQuelle(quelle)}
                />
              ))
            )}
          </TabsContent>

          <TabsContent value="all" className="flex-1 overflow-y-auto p-4 space-y-3 mt-0">
            {filteredQuellen.length === 0 ? (
              <div className="text-center py-8 text-sm text-muted-foreground">
                {searchQuery ? (
                  <p>Keine Quellen gefunden.</p>
                ) : (
                  <>
                    <p>Keine Quellen vorhanden.</p>
                    <p className="mt-1">Erstelle deine erste Quelle.</p>
                  </>
                )}
              </div>
            ) : (
              <>
                {assignedQuellen.length > 0 && (
                  <div className="mb-2">
                    <div className="text-xs font-medium text-muted-foreground mb-2">Zugewiesen</div>
                    {assignedQuellen.map((quelle) => (
                      <QuelleCard
                        key={quelle.id}
                        quelle={quelle}
                        isAssigned={true}
                        onToggleAssign={() => onUnassignQuelle(quelle.id)}
                        onDelete={() => onDeleteQuelle(quelle.id, quelle.name)}
                        onView={() => onViewQuelle(quelle)}
                      />
                    ))}
                  </div>
                )}
                {unassignedQuellen.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-2">Nicht zugewiesen</div>
                    {unassignedQuellen.map((quelle) => (
                      <QuelleCard
                        key={quelle.id}
                        quelle={quelle}
                        isAssigned={false}
                        onToggleAssign={() => onAssignQuelle(quelle.id)}
                        onDelete={() => onDeleteQuelle(quelle.id, quelle.name)}
                        onView={() => onViewQuelle(quelle)}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </TabsContent>
        </Tabs>

        {/* Add Button */}
        <div className="p-4 border-t border-border">
          <Button className="w-full" onClick={() => setAddDialogOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Neue Quelle hinzufügen
          </Button>
        </div>
      </div>

      {/* Add Quelle Dialog */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Neue Quelle hinzufügen</DialogTitle>
          </DialogHeader>
          <div className="py-4 space-y-4">
            <div>
              <Label htmlFor="quelle-name" className="text-sm text-muted-foreground">
                Name der Quelle
              </Label>
              <Input
                id="quelle-name"
                value={newQuelleName}
                onChange={(e) => setNewQuelleName(e.target.value)}
                placeholder="z.B. Müller (2023): Digitale Transformation"
                className="mt-2"
              />
            </div>
            <div>
              <Label htmlFor="quelle-text" className="text-sm text-muted-foreground">
                Text der Quelle (bis zu 4000+ Wörter)
              </Label>
              <Textarea
                id="quelle-text"
                value={newQuelleText}
                onChange={(e) => setNewQuelleText(e.target.value)}
                placeholder="Füge hier den relevanten Textabschnitt aus deiner Quelle ein..."
                className="mt-2 min-h-[300px] font-mono text-sm"
              />
              <div className="mt-2 text-xs text-muted-foreground">
                {newQuelleText.split(/\s+/).filter(Boolean).length} Wörter
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button onClick={handleAddQuelle} disabled={!newQuelleName.trim() || !newQuelleText.trim()}>
              Quelle hinzufügen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function QuelleCard({
  quelle,
  isAssigned,
  onToggleAssign,
  onDelete,
  onView,
}: {
  quelle: Quelle
  isAssigned: boolean
  onToggleAssign: () => void
  onDelete: () => void
  onView: () => void
}) {
  const wordCount = quelle.text.split(/\s+/).filter(Boolean).length

  return (
    <Card className={cn("p-3 transition-colors mb-2", isAssigned ? "bg-primary/5 border-primary/20" : "bg-card")}>
      <div className="flex items-start gap-3">
        <button
          onClick={onToggleAssign}
          className={cn(
            "mt-0.5 w-5 h-5 rounded border flex items-center justify-center transition-colors shrink-0",
            isAssigned ? "bg-primary border-primary text-primary-foreground" : "border-border hover:border-primary",
          )}
        >
          {isAssigned && <Check className="h-3 w-3" />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-foreground truncate">{quelle.name}</div>
          <div className="text-xs text-muted-foreground mt-1">{wordCount.toLocaleString("de-DE")} Wörter</div>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onView}>
            <Eye className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
            onClick={onDelete}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </Card>
  )
}
