"use client"

import { useState } from "react"
import Link from "next/link"
import { ChevronDown, FolderOpen, Plus, LogOut, User, Loader2, BookOpen, RotateCcw, FileDown, Bell } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { toast } from "sonner"
import { useAuth } from "@/app/components/providers/AuthProvider"
import { signOut as signOutUser } from "@/app/lib/firebase/auth"
import type { Projekt } from "@/app/types/ui"

interface ProjektHeaderProps {
  projekt: Projekt
  projekte: Projekt[]
  onSwitchProjekt: (id: string) => void
  onCreateProjekt: (name: string) => Promise<void>
  onArchiveProjekt: (id: string, name: string) => void
  onUnarchiveProjekt: (id: string) => void
  isCreatingProjekt: boolean
  onOpenExport: () => void
  isExporting: boolean
}

export function ProjektHeader({
  projekt,
  projekte,
  onSwitchProjekt,
  onCreateProjekt,
  onArchiveProjekt,
  onUnarchiveProjekt,
  isCreatingProjekt,
  onOpenExport,
  isExporting,
}: ProjektHeaderProps) {
  const { user } = useAuth()
  const [newProjektDialogOpen, setNewProjektDialogOpen] = useState(false)
  const [switchDialogOpen, setSwitchDialogOpen] = useState(false)
  const [newProjektName, setNewProjektName] = useState("")
  const [localCreateLoading, setLocalCreateLoading] = useState(false)

  const activeProjekte = projekte.filter((p) => p.archived !== true)
  const archivedProjekte = projekte.filter((p) => p.archived === true)

  const userName = user?.displayName || user?.email || "User"
  const handleCreateProjekt = async () => {
    if (!newProjektName.trim() || localCreateLoading || isCreatingProjekt) return

    const normalize = (value: string) => value.trim().replace(/\s+/g, " ").toLowerCase()
    const desired = normalize(newProjektName)
    const existing = projekte.some((p) => normalize(p.name) === desired)
    if (existing) {
      toast.error("Projektname bereits vergeben", { description: "Ein Projekt mit diesem Namen existiert bereits (auch im Archiv)." })
      return
    }

    setLocalCreateLoading(true)
    setNewProjektDialogOpen(false)
    try {
      await onCreateProjekt(newProjektName.trim())
      setNewProjektName("")
    } finally {
      setLocalCreateLoading(false)
    }
  }

  const handleSignOut = async () => {
    try {
      await signOutUser()
      window.location.href = "/login"
    } catch (error) {
      console.error("Sign out error:", error)
      toast.error("Fehler beim Abmelden")
    }
  }

  const initials = userName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2)

  return (
    <>
      <div className="p-4 border-b border-sidebar-border">
        {/* App branding and user section combined */}
        <div className="flex items-center justify-between mb-4">
          <span className="text-base font-semibold tracking-tight text-sidebar-foreground">InstantPaper</span>

          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onOpenExport}
              disabled={isExporting}
              title="Export (DOCX)"
              className="h-8 w-8"
            >
              {isExporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
            </Button>

            <Button
              type="button"
              variant="ghost"
              size="icon"
              title="Benachrichtigungen"
              className="h-8 w-8"
            >
              <Bell className="h-4 w-4" />
            </Button>

            {/* User avatar with dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-xs font-medium text-muted-foreground hover:bg-muted/80 transition-colors">
                  {initials}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <div className="px-2 py-1.5 text-sm font-medium">{userName}</div>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/profil" className="flex items-center cursor-pointer">
                    <User className="mr-2 h-4 w-4" />
                    Profil
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link href="/quellen-manager" className="flex items-center cursor-pointer">
                    <BookOpen className="mr-2 h-4 w-4" />
                    Quellen-Manager
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleSignOut} className="text-destructive focus:text-destructive">
                  <LogOut className="mr-2 h-4 w-4" />
                  Abmelden
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Project selector */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="w-full justify-between h-auto py-2.5 px-3 hover:bg-sidebar-accent text-sidebar-foreground"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="text-sm font-medium truncate text-left">{projekt.name}</span>
              </div>
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuItem onClick={() => setSwitchDialogOpen(true)}>
              <FolderOpen className="mr-2 h-4 w-4" />
              Projekt wechseln
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setNewProjektDialogOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Neues Projekt
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* New Project Dialog */}
      <Dialog open={newProjektDialogOpen} onOpenChange={setNewProjektDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Neues Projekt erstellen</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Label htmlFor="projekt-name" className="text-sm text-muted-foreground">
              Wie heißt deine Arbeit?
            </Label>
            <Input
              id="projekt-name"
              value={newProjektName}
              onChange={(e) => setNewProjektName(e.target.value)}
              placeholder="z.B. Masterarbeit: Digitalisierung im Mittelstand"
              className="mt-2"
              onKeyDown={(e) => {
                if (e.key === "Enter" && newProjektName.trim()) {
                  handleCreateProjekt()
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewProjektDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button
              onClick={handleCreateProjekt}
              disabled={!newProjektName.trim() || localCreateLoading}
            >
              {localCreateLoading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Erstellen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Switch Project Dialog */}
      <Dialog open={switchDialogOpen} onOpenChange={setSwitchDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Projekt wechseln</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Tabs defaultValue="active">
              <TabsList className="w-full grid grid-cols-2">
                <TabsTrigger value="active">Aktiv</TabsTrigger>
                <TabsTrigger value="archived">Archiviert</TabsTrigger>
              </TabsList>

              <TabsContent value="active" className="mt-4 space-y-2">
                {activeProjekte.map((p) => (
                  <div
                    key={p.id}
                    className={`w-full px-4 py-3 rounded-md border transition-colors ${
                      p.id === projekt.id ? "bg-primary/10 border-primary/30" : "hover:bg-muted"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <button
                        className="text-left flex-1"
                        onClick={() => {
                          onSwitchProjekt(p.id)
                          setSwitchDialogOpen(false)
                        }}
                      >
                        <div className="font-medium text-sm">{p.name}</div>
                        <div className="text-xs text-muted-foreground mt-1">
                          Erstellt: {p.createdAt.toLocaleDateString("de-DE")}
                        </div>
                      </button>
                      {activeProjekte.length > 1 && p.id !== "default" && (
                        <button
                          className="text-xs text-muted-foreground underline hover:text-foreground"
                          onClick={() => {
                            onArchiveProjekt(p.id, p.name)
                            setSwitchDialogOpen(false)
                          }}
                        >
                          Archivieren
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </TabsContent>

              <TabsContent value="archived" className="mt-4 space-y-2">
                {archivedProjekte.length === 0 ? (
                  <div className="text-sm text-muted-foreground">Keine archivierten Projekte.</div>
                ) : (
                  archivedProjekte.map((p) => (
                    <div key={p.id} className="w-full px-4 py-3 rounded-md border bg-muted/30">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="font-medium text-sm truncate">{p.name}</div>
                          <div className="text-xs text-muted-foreground mt-1">
                            Erstellt: {p.createdAt.toLocaleDateString("de-DE")}
                          </div>
                        </div>
                        <Button variant="outline" size="sm" onClick={() => onUnarchiveProjekt(p.id)}>
                          <RotateCcw className="h-4 w-4 mr-2" />
                          Wiederherstellen
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </TabsContent>
            </Tabs>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
