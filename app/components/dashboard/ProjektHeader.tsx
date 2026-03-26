"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import {
  Archive,
  CalendarDays,
  ChevronDown,
  Clock3,
  FolderOpen,
  Plus,
  LogOut,
  Pencil,
  User,
  Loader2,
  BookOpen,
  RotateCcw,
  FileDown,
  Search,
  FileText,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { toast } from "sonner"
import { useAuth } from "@/app/components/providers/AuthProvider"
import { signOut as signOutUser } from "@/app/lib/firebase/auth"
import { fetchBillingBalance } from "@/app/lib/api/billingClient"
import type { Projekt } from "@/app/types/ui"

const normalizeProjektName = (value: string) => value.trim().replace(/\s+/g, " ").toLowerCase()

interface ProjektHeaderProps {
  projekt: Projekt
  projekte: Projekt[]
  onSwitchProjekt: (id: string) => void
  onCreateProjekt: (name: string) => Promise<void>
  onRenameProjekt: (id: string, name: string) => Promise<{ success: boolean; error?: string }>
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
  onRenameProjekt,
  onArchiveProjekt,
  onUnarchiveProjekt,
  isCreatingProjekt,
  onOpenExport,
  isExporting,
}: ProjektHeaderProps) {
  const { user, canUsePdfScan, canUseQuellenFinder } = useAuth()
  const [newProjektDialogOpen, setNewProjektDialogOpen] = useState(false)
  const [switchDialogOpen, setSwitchDialogOpen] = useState(false)
  const [switchTab, setSwitchTab] = useState<"active" | "archived">("active")
  const [newProjektName, setNewProjektName] = useState("")
  const [localCreateLoading, setLocalCreateLoading] = useState(false)
  const [renameDialogOpen, setRenameDialogOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState<Projekt | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [renameSaving, setRenameSaving] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [totalCredits, setTotalCredits] = useState<number | null>(null)
  const [creditsLoading, setCreditsLoading] = useState(false)
  const lastCreditsFetchRef = useRef<number>(0)

  const activeProjekte = projekte.filter((p) => p.archived !== true)
  const archivedProjekte = projekte.filter((p) => p.archived === true)
  const activeCount = activeProjekte.length
  const archivedCount = archivedProjekte.length

  const userName = user?.displayName || user?.email || "User"

  const creditsLabel = (() => {
    const n = Number(totalCredits ?? 0)
    if (!Number.isFinite(n)) return "-"
    const abs = Math.abs(n)
    const maximumFractionDigits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2
    return n.toLocaleString("de-DE", { maximumFractionDigits })
  })()

  useEffect(() => {
    if (!userMenuOpen) return
    if (!user?.uid) return

    const now = Date.now()
    if (totalCredits != null && now - lastCreditsFetchRef.current < 15_000) return

    setCreditsLoading(true)
    fetchBillingBalance()
      .then((bal) => {
        // Always show Gesamt-Credits (do not subtract reserved credits).
        setTotalCredits(Number(bal.totalCredits ?? 0))
        lastCreditsFetchRef.current = now
      })
      .catch((err) => {
        console.error("Failed to load billing balance:", err)
        setTotalCredits(null)
      })
      .finally(() => setCreditsLoading(false))
  }, [userMenuOpen, user?.uid, totalCredits])

  useEffect(() => {
    if (!switchDialogOpen) return
    setSwitchTab("active")
  }, [switchDialogOpen])

  const handleCreateProjekt = async () => {
    if (!newProjektName.trim() || localCreateLoading || isCreatingProjekt) return

    const desired = normalizeProjektName(newProjektName)
    const existing = projekte.some((p) => normalizeProjektName(p.name) === desired)
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

  const formatDate = (d: Date) =>
    d.toLocaleDateString("de-DE", { day: "2-digit", month: "short", year: "numeric" })

  const openRename = (p: Projekt) => {
    setRenameTarget(p)
    setRenameValue(p.name)
    setRenameDialogOpen(true)
  }

  const renameValidationError = useMemo(() => {
    if (!renameDialogOpen) return null

    const desired = renameValue.trim()
    if (!desired) return "Projektname darf nicht leer sein."
    const desiredNorm = normalizeProjektName(desired)
    const hasDuplicate = projekte.some((p) => p.id !== renameTarget?.id && normalizeProjektName(p.name) === desiredNorm)
    if (hasDuplicate) return "Ein Projekt mit diesem Namen existiert bereits (auch im Archiv)."

    return null
  }, [projekte, renameDialogOpen, renameTarget?.id, renameValue])

  const handleRenameProjekt = async () => {
    if (renameSaving) return
    if (!renameTarget) return

    const desired = renameValue.trim()
    if (!desired || renameValidationError) return

    setRenameSaving(true)
    try {
      const result = await onRenameProjekt(renameTarget.id, desired)
      if (!result.success) {
        throw new Error(result.error || "Projekt konnte nicht umbenannt werden.")
      }
      setRenameDialogOpen(false)
      toast.success("Projekt umbenannt")
    } catch (error) {
      console.error("Rename project error:", error)
      toast.error("Projekt umbenennen fehlgeschlagen", {
        description: error instanceof Error ? error.message : "Bitte versuche es erneut.",
      })
    } finally {
      setRenameSaving(false)
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

            {/* User avatar with dropdown */}
            <DropdownMenu open={userMenuOpen} onOpenChange={setUserMenuOpen}>
              <DropdownMenuTrigger asChild>
                <button className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-xs font-medium text-muted-foreground hover:bg-muted/80 transition-colors">
                  {initials}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <div className="px-2 py-1.5 text-sm font-medium">{userName}</div>
                <div className="px-2 pb-2">
                  <div className="flex items-center justify-between rounded-md bg-muted/40 px-2 py-1">
                    <span className="text-xs text-muted-foreground">Credits</span>
                    <span className="text-xs font-semibold tabular-nums">
                      {creditsLoading ? "…" : totalCredits == null ? "-" : creditsLabel}
                    </span>
                  </div>
                </div>
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
                {canUseQuellenFinder ? (
                  <DropdownMenuItem asChild>
                    <Link href="/quellen-finder" className="flex items-center cursor-pointer">
                      <Search className="mr-2 h-4 w-4" />
                      Quellen-Finder
                    </Link>
                  </DropdownMenuItem>
                ) : null}
                {canUsePdfScan ? (
                  <DropdownMenuItem asChild>
                    <Link href="/pdf-scan" className="flex items-center cursor-pointer">
                      <FileText className="mr-2 h-4 w-4" />
                      PDF-Scan
                    </Link>
                  </DropdownMenuItem>
                ) : null}
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
                Projekte verwalten
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
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Projekte verwalten</DialogTitle>
            <DialogDescription>
              {activeCount} aktive, {archivedCount} archivierte Projekte
            </DialogDescription>
          </DialogHeader>
          <div className="pt-2 space-y-4">
            <Tabs value={switchTab} onValueChange={(v) => setSwitchTab(v as "active" | "archived")}>
              <TabsList className="w-full justify-start gap-6 bg-transparent p-0 h-auto rounded-none border-b">
                <TabsTrigger
                  value="active"
                  className="px-0 py-2 rounded-none border-x-0 border-t-0 border-b-2 border-transparent bg-transparent data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-foreground data-[state=active]:border-primary text-muted-foreground"
                >
                  Aktive ({activeCount})
                </TabsTrigger>
                <TabsTrigger
                  value="archived"
                  className="px-0 py-2 rounded-none border-x-0 border-t-0 border-b-2 border-transparent bg-transparent data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-foreground data-[state=active]:border-primary text-muted-foreground"
                >
                  Archiviert ({archivedCount})
                </TabsTrigger>
              </TabsList>

              <TabsContent value="active" className="mt-4 space-y-3">
                {activeProjekte.map((p) => {
                  const isCurrent = p.id === projekt.id
                  const canArchive = activeCount > 1 && p.id !== "default"
                  const updated = p.updatedAt ?? p.createdAt
                  return (
                    <div
                      key={p.id}
                      className={`w-full rounded-lg border p-4 transition-colors ${
                        isCurrent ? "bg-primary/10 border-primary/40" : "hover:bg-muted/40"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 min-w-0">
                            <div className="font-medium text-sm truncate">{p.name}</div>
                            {isCurrent ? (
                              <Badge className="bg-sky-100 text-sky-800 hover:bg-sky-100">Aktuell</Badge>
                            ) : null}
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                            <div className="flex items-center gap-1.5">
                              <CalendarDays className="h-3.5 w-3.5" />
                              {formatDate(p.createdAt)}
                            </div>
                            <div className="flex items-center gap-1.5">
                              <Clock3 className="h-3.5 w-3.5" />
                              {formatDate(updated)}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-1 shrink-0">
                          {!isCurrent ? (
                            <button
                              className="text-sm font-medium text-muted-foreground hover:text-foreground px-2 py-1"
                              onClick={() => {
                                onSwitchProjekt(p.id)
                                setSwitchDialogOpen(false)
                              }}
                            >
                              Öffnen
                            </button>
                          ) : null}

                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => openRename(p)}
                            title="Umbenennen"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>

                          {canArchive ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => {
                                onArchiveProjekt(p.id, p.name)
                                setSwitchDialogOpen(false)
                              }}
                              title="Archivieren"
                            >
                              <Archive className="h-4 w-4" />
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </TabsContent>

              <TabsContent value="archived" className="mt-4 space-y-3">
                {archivedProjekte.length === 0 ? (
                  <div className="text-sm text-muted-foreground">Keine archivierten Projekte.</div>
                ) : (
                  archivedProjekte.map((p) => {
                    const updated = p.updatedAt ?? p.createdAt
                    return (
                      <div key={p.id} className="w-full rounded-lg border p-4 bg-muted/20">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="font-medium text-sm truncate">{p.name}</div>
                            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                              <div className="flex items-center gap-1.5">
                                <CalendarDays className="h-3.5 w-3.5" />
                                {formatDate(p.createdAt)}
                              </div>
                              <div className="flex items-center gap-1.5">
                                <Clock3 className="h-3.5 w-3.5" />
                                {formatDate(updated)}
                              </div>
                            </div>
                          </div>

                          <div className="flex items-center gap-1 shrink-0">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => onUnarchiveProjekt(p.id)}
                              title="Wiederherstellen"
                            >
                              <RotateCcw className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </TabsContent>
            </Tabs>

            <div className="text-xs text-muted-foreground">
              <span className="font-medium">Hinweis:</span> Archivierte Projekte können jederzeit wiederhergestellt werden.
              Zum Löschen von Projekten besuche deine Profilseite.
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={renameDialogOpen}
        onOpenChange={(open) => {
          setRenameDialogOpen(open)
          if (!open) {
            setRenameTarget(null)
            setRenameValue("")
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Projekt umbenennen</DialogTitle>
            <DialogDescription>Gib einen neuen Namen für dein Projekt ein.</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="rename-projekt-name">Name</Label>
            <Input
              id="rename-projekt-name"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder="z.B. Masterarbeit: Digitalisierung im Mittelstand"
              maxLength={200}
              disabled={renameSaving}
            />
            {renameValidationError ? (
              <p className="text-xs text-destructive">{renameValidationError}</p>
            ) : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameDialogOpen(false)} disabled={renameSaving}>
              Abbrechen
            </Button>
            <Button onClick={handleRenameProjekt} disabled={renameSaving || Boolean(renameValidationError)}>
              {renameSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Speichern
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
