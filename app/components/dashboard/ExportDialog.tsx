"use client"

import { useEffect, useMemo, useState } from "react"
import { Download, FileText, Loader2, AlertCircle } from "lucide-react"
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
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import type { Kapitel } from "@/app/types/ui"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { getKapitelsWithLeseflussText } from "@/app/actions/kapitels"

type ExportSelection = "all" | "selected"

interface ExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  allKapitels: Kapitel[]
  projektId: string
  onExport: (selection: ExportSelection, kapitelIds: string[], includeFootnotes: boolean) => Promise<void>
  isExporting: boolean
}

export function ExportDialog({
  open,
  onOpenChange,
  allKapitels,
  projektId,
  onExport,
  isExporting,
}: ExportDialogProps) {
  const [selection, setSelection] = useState<ExportSelection>("all")
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [includeFootnotes, setIncludeFootnotes] = useState(true)
  const [availability, setAvailability] = useState<Record<string, boolean> | null>(null)
  const [availabilityLoading, setAvailabilityLoading] = useState(false)
  const [localExportLoading, setLocalExportLoading] = useState(false)

  const sortedKapiteln = useMemo(() => {
    const list = allKapitels.slice()
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
  }, [allKapitels])

  useEffect(() => {
    if (!open) {
      setAvailability(null)
      setAvailabilityLoading(false)
      setSelection("all")
      setSelectedIds([])
      setIncludeFootnotes(true)
      return
    }

    if (!projektId) return

    const ids = sortedKapiteln.map((k) => k.id)
    if (ids.length === 0) {
      setAvailability({})
      return
    }

    let cancelled = false
    setAvailabilityLoading(true)
    getKapitelsWithLeseflussText(ids)
      .then((result) => {
        if (cancelled) return
        setAvailability(result)
      })
      .catch((err) => {
        console.error("Failed to check Kapitel lesefluss availability", err)
        if (cancelled) return
        setAvailability({})
      })
      .finally(() => {
        if (cancelled) return
        setAvailabilityLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [open, sortedKapiteln, projektId])

  const hasLeseflussText = (kapitelId: string) => {
    if (availabilityLoading || !availability) return false
    return Boolean(availability[kapitelId])
  }

  const availableIds = useMemo(() => {
    if (!availability || availabilityLoading) return []
    return sortedKapiteln.filter((k) => Boolean(availability[k.id])).map((k) => k.id)
  }, [availability, availabilityLoading, sortedKapiteln])

  useEffect(() => {
    if (!open) return
    if (selection !== "all") return
    if (availabilityLoading) return
    setSelectedIds(availableIds)
  }, [open, selection, availabilityLoading, availableIds])

  const toggleKapitel = (id: string) => {
    if (!hasLeseflussText(id)) return
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]))
  }

  const setSelectionMode = (next: ExportSelection) => {
    setSelection(next)
    if (next === "all") {
      setSelectedIds(availableIds)
    }
  }

  const handleExport = async () => {
    if (!projektId) return
    if (selectedIds.length === 0) return
    if (localExportLoading || isExporting) return
    setLocalExportLoading(true)
    onOpenChange(false)
    try {
      await onExport(selection, selectedIds, includeFootnotes)
    } finally {
      setLocalExportLoading(false)
    }
  }

  const getIndentLevel = (nummer: string) => nummer.split(".").length - 1

  const disabled = selectedIds.length === 0 || localExportLoading || isExporting
  const availabilityKnown = !availabilityLoading && availability !== null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" showCloseButton={false}>
        <DialogHeader className="pb-4 border-b">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <FileText className="h-4 w-4 text-primary" />
            </div>
            Export (DOCX)
          </DialogTitle>
          <DialogDescription className="pt-1">
            Exportiert alle vorhandenen „Verbesserten Texte“ (Lesefluss) als Word-Datei. Der Export ist nur kurze Zeit verfügbar.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4 space-y-4">
          <div className="grid grid-cols-2 gap-2">
            <Button
              type="button"
              variant={selection === "all" ? "default" : "outline"}
              onClick={() => setSelectionMode("all")}
              disabled={availabilityLoading}
            >
              Ganzes Projekt
            </Button>
            <Button
              type="button"
              variant={selection === "selected" ? "default" : "outline"}
              onClick={() => setSelectionMode("selected")}
              disabled={availabilityLoading}
            >
              Auswahl
            </Button>
          </div>

          <p className="text-sm text-muted-foreground">
            Nur Kapitel mit vorhandenem „Verbesserten Text“ können exportiert werden.
          </p>

          <div className="flex items-center justify-between py-3 px-4 border bg-muted/20 rounded-lg">
            <div className="flex items-start gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <Label htmlFor="export-footnotes" className="text-sm font-medium cursor-pointer">
                    Quellen als Fußnoten einfügen
                  </Label>
                  <span
                    className={cn(
                      "text-xs font-medium px-2 py-0.5 rounded-md border",
                      includeFootnotes
                        ? "border-border bg-muted/40 text-muted-foreground"
                        : "border-border bg-background text-muted-foreground",
                    )}
                  >
                    {includeFootnotes ? "Aktiviert" : "Deaktiviert"}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Wenn deaktiviert, bleiben Quellen/Zitate im Text und es werden keine Fußnoten erstellt.
                </p>
              </div>
            </div>
            <Switch id="export-footnotes" checked={includeFootnotes} onCheckedChange={setIncludeFootnotes} />
          </div>

          {selection === "selected" && (
            <div className="border rounded-lg max-h-[320px] overflow-y-auto">
              <TooltipProvider>
                {sortedKapiteln.map((kapitel) => {
                  const hasText = hasLeseflussText(kapitel.id)
                  const isSelected = selectedIds.includes(kapitel.id)
                  const indentLevel = getIndentLevel(kapitel.nummer)

                  return (
                    <Tooltip key={kapitel.id}>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          className={cn(
                            "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors border-b last:border-b-0",
                            hasText && "hover:bg-muted/50 cursor-pointer",
                            !hasText && "opacity-50 cursor-not-allowed",
                            isSelected && "bg-primary/10",
                          )}
                          onClick={() => toggleKapitel(kapitel.id)}
                          disabled={!hasText}
                          style={{ paddingLeft: `${16 + indentLevel * 20}px` }}
                        >
                          <div
                            className={cn(
                              "w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors",
                              isSelected
                                ? "bg-primary border-primary"
                                : hasText
                                  ? "border-muted-foreground/30"
                                  : "border-muted-foreground/20 bg-muted/30",
                            )}
                          />
                          <div className="flex-1 min-w-0">
                            <span className="text-sm">
                              <span className="text-muted-foreground mr-1.5">{kapitel.nummer}</span>
                              <span className={cn(!hasText && "text-muted-foreground")}>{kapitel.title}</span>
                            </span>
                          </div>
                          {!hasText && <AlertCircle className="h-4 w-4 text-muted-foreground/50 shrink-0" />}
                        </button>
                      </TooltipTrigger>
                      {!hasText && (
                        <TooltipContent side="left">
                          <p>
                            {!availabilityKnown
                              ? "Prüfe Text..."
                              : "Dieses Kapitel hat noch keinen verbesserten Text"}
                          </p>
                        </TooltipContent>
                      )}
                    </Tooltip>
                  )
                })}
              </TooltipProvider>
            </div>
          )}

          <div className="text-xs text-muted-foreground">
            Hinweis: Der Export bleibt ca. 7 Tage verfügbar. Bitte lade die Datei zeitnah herunter.
          </div>
        </div>

        <DialogFooter className="pt-4 border-t gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button onClick={handleExport} disabled={disabled}>
            {localExportLoading || isExporting ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Download className="h-4 w-4 mr-2" />
            )}
            Export starten ({selectedIds.length})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
