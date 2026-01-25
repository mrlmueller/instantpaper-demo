"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { AlertTriangle, CheckCircle2, FileText, Loader2, Plus, RotateCcw, Save } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Progress } from "@/components/ui/progress"
import { Checkbox } from "@/components/ui/checkbox"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { GliederungDraft, GliederungDraftOutput } from "@/app/types/gliederung"
import { cn } from "@/lib/utils"

type KapitelValidation = {
  duplicateIds: Set<string>
  invalidIds: Set<string>
  tooDeepIds: Set<string>
  jumpWarnings: string[]
  missingParentWarnings: string[]
}

function formatDraftLabel(draft: GliederungDraft): string {
  const d = draft.createdAt
  const stamp = d instanceof Date ? d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "—"
  const status = draft.status === "running" ? "läuft" : draft.status === "success" ? "fertig" : "fehler"
  return `${stamp} · ${status}`
}

function validateKapitel(output: GliederungDraftOutput | null | undefined): KapitelValidation {
  const chapters = output?.kapitel ?? []
  const counts = new Map<string, number>()
  const nummerById = new Map<string, string>()
  const duplicateIds = new Set<string>()
  const invalidIds = new Set<string>()
  const tooDeepIds = new Set<string>()

  for (const ch of chapters) {
    const nummer = String(ch?.nummer ?? "").trim()
    nummerById.set(ch.id, nummer)
    if (!nummer) {
      invalidIds.add(ch.id)
      continue
    }
    counts.set(nummer, (counts.get(nummer) ?? 0) + 1)

    const parts = nummer.split(".")
    if (parts.length > 3) {
      tooDeepIds.add(ch.id)
      invalidIds.add(ch.id)
      continue
    }
    const ok = parts.every((p) => /^[1-9]\d*$/.test(p))
    if (!ok) {
      invalidIds.add(ch.id)
    }
  }

  for (const [nummer, count] of counts.entries()) {
    if (count <= 1) continue
    for (const [id, n] of nummerById.entries()) {
      if (n === nummer) duplicateIds.add(id)
    }
  }

  const valid = chapters
    .map((ch) => {
      const nummer = String(ch?.nummer ?? "").trim()
      const parts = nummer ? nummer.split(".") : []
      const ok =
        parts.length > 0 && parts.length <= 3 && parts.every((p) => /^[1-9]\d*$/.test(p)) && !duplicateIds.has(ch.id)
      return ok
        ? {
            id: ch.id,
            nummer,
            parts: parts.map((p) => Number(p)),
          }
        : null
    })
    .filter(Boolean) as Array<{ id: string; nummer: string; parts: number[] }>

  const existing = new Set(valid.map((v) => v.nummer))
  const missingParentWarnings: string[] = []
  for (const v of valid) {
    if (v.parts.length <= 1) continue
    const parent = v.parts.slice(0, -1).join(".")
    if (!existing.has(parent)) missingParentWarnings.push(v.nummer)
  }

  const groups = new Map<string, number[]>()
  for (const v of valid) {
    const prefix = v.parts.slice(0, -1).join(".")
    const last = v.parts[v.parts.length - 1]
    const list = groups.get(prefix) ?? []
    list.push(last)
    groups.set(prefix, list)
  }

  const jumpWarnings: string[] = []
  for (const [prefix, nums] of groups.entries()) {
    const uniq = Array.from(new Set(nums)).sort((a, b) => a - b)
    if (uniq.length <= 1) continue
    let hasJump = false
    for (let i = 0; i < uniq.length; i++) {
      const expected = i === 0 ? 1 : uniq[i - 1] + 1
      if (uniq[i] !== expected) {
        hasJump = true
        break
      }
    }
    if (hasJump) jumpWarnings.push(prefix || "Hauptkapitel")
  }

  return { duplicateIds, invalidIds, tooDeepIds, jumpWarnings, missingParentWarnings }
}

interface GliederungWorkspaceProps {
  drafts: GliederungDraft[]
  selectedDraftId: string | null
  onSelectDraft: (id: string) => void
  onOpenCreate: () => void
  onStartOver: () => Promise<void>
  onRestoreDraft: (id: string) => Promise<void>
  onUpdateDraftOutput: (draftId: string, output: GliederungDraftOutput) => Promise<void>
  onApplyDraft: (draftId: string, output: GliederungDraftOutput) => Promise<void>
  isApplying: boolean
}

export function GliederungWorkspace({
  drafts,
  selectedDraftId,
  onSelectDraft,
  onOpenCreate,
  onStartOver,
  onRestoreDraft,
  onUpdateDraftOutput,
  onApplyDraft,
  isApplying,
}: GliederungWorkspaceProps) {
  const activeDrafts = useMemo(() => {
    return drafts
      .filter((d) => !d.archived)
      .slice()
      .sort((a, b) => (b.updatedAt?.valueOf?.() || 0) - (a.updatedAt?.valueOf?.() || 0))
  }, [drafts])

  const archivedDrafts = useMemo(() => {
    return drafts
      .filter((d) => d.archived)
      .slice()
      .sort((a, b) => (b.archivedAt?.valueOf?.() || 0) - (a.archivedAt?.valueOf?.() || 0))
  }, [drafts])

  const selectedDraft = useMemo(() => {
    if (!selectedDraftId) return null
    return drafts.find((d) => d.id === selectedDraftId) ?? null
  }, [drafts, selectedDraftId])

  useEffect(() => {
    if (selectedDraftId) return
    if (activeDrafts.length === 0) return
    onSelectDraft(activeDrafts[0].id)
  }, [activeDrafts, onSelectDraft, selectedDraftId])

  const [startOverConfirmOpen, setStartOverConfirmOpen] = useState(false)
  const [archiveDialogOpen, setArchiveDialogOpen] = useState(false)

  const [output, setOutput] = useState<GliederungDraftOutput | null>(selectedDraft?.output ?? null)
  const [version, setVersion] = useState(0)
  const savedVersionRef = useRef(0)
  const attemptedVersionRef = useRef(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    setOutput(null)
    setVersion(0)
    savedVersionRef.current = 0
    attemptedVersionRef.current = 0
    setSaving(false)
    setSaveError(null)
  }, [selectedDraft?.id])

  useEffect(() => {
    if (output) return
    if (selectedDraft?.output) {
      setOutput(selectedDraft.output)
    }
  }, [output, selectedDraft?.output])

  const validation = useMemo(() => validateKapitel(output), [output])

  const chapters = output?.kapitel ?? []
  const total = chapters.length
  const reviewedCount = chapters.filter((c) => c.reviewed).length
  const reviewProgress = total > 0 ? Math.round((reviewedCount / total) * 100) : 0

  const hasBlockingErrors = validation.duplicateIds.size > 0 || validation.invalidIds.size > 0 || validation.tooDeepIds.size > 0
  const allReviewed = total > 0 && reviewedCount === total
  const isDirty = version !== savedVersionRef.current

  const bumpVersion = () => setVersion((v) => v + 1)

  const updateKapitel = (id: string, patch: Partial<GliederungDraftOutput["kapitel"][number]>) => {
    setOutput((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        kapitel: prev.kapitel.map((ch) => (ch.id === id ? { ...ch, ...patch } : ch)),
      }
    })
    bumpVersion()
  }

  useEffect(() => {
    if (!selectedDraft || !output) return
    if (version === savedVersionRef.current) return
    if (saving) return
    if (version === attemptedVersionRef.current) return

    const t = setTimeout(async () => {
      if (!selectedDraft || !output) return
      const versionToSave = version
      attemptedVersionRef.current = versionToSave
      setSaving(true)
      try {
        await onUpdateDraftOutput(selectedDraft.id, output)
        savedVersionRef.current = versionToSave
        setSaveError(null)
      } catch (err: unknown) {
        setSaveError(err instanceof Error ? err.message : "Speichern fehlgeschlagen.")
      } finally {
        setSaving(false)
      }
    }, 800)

    return () => clearTimeout(t)
  }, [onUpdateDraftOutput, output, saving, selectedDraft, version])

  const handleSaveNow = async () => {
    if (!selectedDraft || !output || saving) return
    setSaving(true)
    setSaveError(null)
    try {
      await onUpdateDraftOutput(selectedDraft.id, output)
      savedVersionRef.current = version
      attemptedVersionRef.current = version
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Speichern fehlgeschlagen.")
    } finally {
      setSaving(false)
    }
  }

  const handleApply = async () => {
    if (!selectedDraft || !output) return
    if (isApplying || saving) return
    if (!allReviewed || hasBlockingErrors) return
    if (isDirty) {
      await handleSaveNow()
      if (version !== savedVersionRef.current) return
    }
    await onApplyDraft(selectedDraft.id, output)
  }

  const header = (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold">Gliederung (Entwurf)</h2>
        <p className="text-sm text-muted-foreground">
          Erstelle einen Entwurf, prüfe ihn sorgfältig und übernimm ihn erst danach als Kapitel.
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button variant="outline" onClick={onOpenCreate}>
          <Plus className="h-4 w-4 mr-2" />
          Neuer Entwurf
        </Button>
        <Button variant="outline" onClick={() => setArchiveDialogOpen(true)} disabled={archivedDrafts.length === 0}>
          Archiv
        </Button>
        <Button variant="destructive" onClick={() => setStartOverConfirmOpen(true)} disabled={drafts.length === 0}>
          <RotateCcw className="h-4 w-4 mr-2" />
          Von vorne beginnen
        </Button>
      </div>
    </div>
  )

  if (activeDrafts.length === 0 && archivedDrafts.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="max-w-xl w-full">
          <Card className="p-6">
            {header}
            <div className="mt-6 space-y-4">
              <p className="text-sm text-muted-foreground">
                Dieses Projekt hat noch keine Kapitel. Du kannst direkt mit einem KI‑Entwurf starten und ihn anschließend
                in Ruhe prüfen.
              </p>
              <Button onClick={onOpenCreate} className="w-full">
                Gliederung erstellen
              </Button>
            </div>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-hidden">
      <div className="h-full overflow-y-auto p-6">
        <div className="max-w-5xl mx-auto space-y-6">
          <Card className="p-6">
            {header}

            {activeDrafts.length > 0 && (
              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label className="text-sm font-medium">Aktiver Entwurf</Label>
                  <Select
                    value={selectedDraft?.id || activeDrafts[0]?.id}
                    onValueChange={(val) => onSelectDraft(val)}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {activeDrafts.map((d) => (
                        <SelectItem key={d.id} value={d.id}>
                          {formatDraftLabel(d)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label className="text-sm font-medium">Review‑Fortschritt</Label>
                  <div className="flex items-center justify-between gap-3">
                    <Progress value={reviewProgress} className="flex-1" />
                    <div className="text-sm tabular-nums">
                      {reviewedCount}/{total}
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{selectedDraft?.model ? `Modell: ${selectedDraft.model}` : ""}</span>
                    <span className={cn(saveError ? "text-destructive" : "")}>
                      {saving ? "Wird gespeichert..." : saveError ? "Nicht gespeichert" : isDirty ? "Ungespeichert" : "Gespeichert"}
                    </span>
                  </div>
                  {(isDirty || saveError) && (
                    <Button variant="outline" size="sm" className="mt-2" onClick={handleSaveNow} disabled={saving || !isDirty}>
                      <Save className="h-4 w-4 mr-2" />
                      Speichern
                    </Button>
                  )}
                  {saveError && <p className="text-xs text-destructive mt-2">{saveError}</p>}
                </div>
              </div>
            )}
          </Card>

          {activeDrafts.length === 0 && archivedDrafts.length > 0 && (
            <Card className="p-6">
              <div className="font-medium">Keine aktiven Entwürfe</div>
              <p className="text-sm text-muted-foreground mt-1">
                Erstelle einen neuen Entwurf oder stelle einen Entwurf aus dem Archiv wieder her.
              </p>
              <div className="mt-4 flex flex-col sm:flex-row gap-2">
                <Button onClick={onOpenCreate} className="sm:w-auto w-full">
                  Neuer Entwurf
                </Button>
                <Button variant="outline" onClick={() => setArchiveDialogOpen(true)} className="sm:w-auto w-full">
                  Archiv öffnen
                </Button>
              </div>
            </Card>
          )}

          {selectedDraft && selectedDraft.status === "running" && (
            <Card className="p-6">
              <div className="flex items-center gap-3">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                <div>
                  <div className="font-medium">Entwurf wird erstellt...</div>
                  <div className="text-sm text-muted-foreground">Sobald er fertig ist, kannst du ihn hier prüfen.</div>
                </div>
              </div>
            </Card>
          )}

          {selectedDraft && selectedDraft.status === "error" && (
            <Card className="p-6 border-destructive/40">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-destructive mt-0.5" />
                <div className="space-y-2">
                  <div className="font-medium">Entwurf konnte nicht erstellt werden</div>
                  <div className="text-sm text-muted-foreground">{selectedDraft.errorMessage || "Unbekannter Fehler."}</div>
                  <Button onClick={onOpenCreate} variant="outline">
                    Neuer Versuch
                  </Button>
                </div>
              </div>
            </Card>
          )}

          {selectedDraft && selectedDraft.status === "success" && output && (
            <>
              {(hasBlockingErrors || validation.jumpWarnings.length > 0 || validation.missingParentWarnings.length > 0) && (
                <Card
                  className={cn(
                    "p-4",
                    hasBlockingErrors ? "border-destructive/40" : "border-yellow-500/30"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <AlertTriangle className={cn("h-5 w-5 mt-0.5", hasBlockingErrors ? "text-destructive" : "text-yellow-600")} />
                    <div className="space-y-2">
                      <div className="font-medium">
                        {hasBlockingErrors ? "Bitte Fehler beheben" : "Hinweise zur Nummerierung"}
                      </div>
                      {validation.duplicateIds.size > 0 && (
                        <p className="text-sm text-muted-foreground">Es gibt doppelte Kapitelnummern.</p>
                      )}
                      {validation.invalidIds.size > 0 && (
                        <p className="text-sm text-muted-foreground">Es gibt ungültige Kapitelnummern (Format: 1, 1.1 oder 1.1.1).</p>
                      )}
                      {validation.tooDeepIds.size > 0 && (
                        <p className="text-sm text-muted-foreground">Die Gliederungstiefe darf maximal Ebene 3 sein.</p>
                      )}
                      {validation.jumpWarnings.length > 0 && (
                        <p className="text-sm text-muted-foreground">
                          Warnung: Es gibt Nummerierungs‑Sprünge (z. B. fehlende 1.2). Das blockiert nicht.
                        </p>
                      )}
                      {validation.missingParentWarnings.length > 0 && (
                        <p className="text-sm text-muted-foreground">
                          Warnung: Unterkapitel ohne passendes Oberkapitel (z. B. 2.1 ohne 2). Das blockiert nicht.
                        </p>
                      )}
                    </div>
                  </div>
                </Card>
              )}

              <Card className="p-6">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <div className="font-medium">Kapitel prüfen</div>
                  </div>
                  <Badge variant={allReviewed ? "default" : "secondary"}>
                    {allReviewed ? "Alles geprüft" : "Bitte alles prüfen"}
                  </Badge>
                </div>

                <div className="mt-4">
                  <Accordion type="multiple" className="w-full">
                    {chapters.map((ch) => {
                      const hasDuplicate = validation.duplicateIds.has(ch.id)
                      const hasInvalid = validation.invalidIds.has(ch.id)
                      const hasError = hasDuplicate || hasInvalid
                      return (
                        <AccordionItem key={ch.id} value={ch.id}>
                          <AccordionTrigger className="hover:no-underline">
                            <div className="flex items-center justify-between gap-3 w-full">
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className={cn("font-mono text-xs text-muted-foreground", hasError && "text-destructive")}>
                                    {ch.nummer?.trim() || "—"}
                                  </span>
                                  <span className={cn("text-sm font-medium truncate", hasError && "text-destructive")}>
                                    {ch.titel?.trim() || "Ohne Titel"}
                                  </span>
                                </div>
                                <div className="text-xs text-muted-foreground mt-0.5">
                                  {ch.seitenumfang?.trim() ? `Seiten: ${ch.seitenumfang.trim()}` : "—"}
                                </div>
                              </div>
                                <div className="flex items-center gap-2 shrink-0">
                                {hasError && (
                                  <Badge variant="outline" className="border-destructive/40 text-destructive">
                                    Fehler
                                  </Badge>
                                )}
                                {ch.reviewed && (
                                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                                    <CheckCircle2 className="h-4 w-4 text-primary" />
                                  </div>
                                )}
                              </div>
                            </div>
                          </AccordionTrigger>
                          <AccordionContent>
                            <div className="grid gap-4 pt-2">
                              <div className="grid gap-3 md:grid-cols-2">
                                <div className="space-y-2">
                                  <Label className="text-sm">Kapitelnummer</Label>
                                  <Input
                                    value={ch.nummer}
                                    onChange={(e) => updateKapitel(ch.id, { nummer: e.target.value })}
                                    className={cn(hasError && "border-destructive")}
                                    placeholder="z.B. 1.2"
                                  />
                                </div>
                                <div className="space-y-2">
                                  <Label className="text-sm">Überschrift</Label>
                                  <Input
                                    value={ch.titel}
                                    onChange={(e) => updateKapitel(ch.id, { titel: e.target.value })}
                                    placeholder="z.B. Einleitung"
                                  />
                                </div>
                              </div>

                              <div className="space-y-2">
                                <Label className="text-sm">Thema & Anweisungen</Label>
                                <Textarea
                                  value={ch.beschreibung}
                                  onChange={(e) => updateKapitel(ch.id, { beschreibung: e.target.value })}
                                  className="min-h-[140px] resize-none"
                                  placeholder="Was soll in diesem Kapitel behandelt werden…"
                                />
                              </div>

                              <div className="grid gap-3 md:grid-cols-2">
                                <div className="space-y-2">
                                  <Label className="text-sm">Seitenumfang</Label>
                                  <Input
                                    value={ch.seitenumfang}
                                    onChange={(e) => updateKapitel(ch.id, { seitenumfang: e.target.value })}
                                    placeholder="z.B. 2–3 Seiten"
                                  />
                                </div>
                                <div className="space-y-2">
                                  <Label className="text-sm">Externe Quellen erforderlich</Label>
                                  <div className="text-sm">
                                    <Badge variant={ch.externeQuellenErforderlich ? "secondary" : "outline"}>
                                      {ch.externeQuellenErforderlich ? "ja" : "nein"}
                                    </Badge>
                                  </div>
                                </div>
                              </div>

                              <div className="space-y-2">
                                <Label className="text-sm">Zusätzlicher Kontext (für separaten KI‑Chat)</Label>
                                <Textarea
                                  value={(ch.kontext || []).join("\n")}
                                  onChange={(e) =>
                                    updateKapitel(ch.id, {
                                      kontext: e.target.value
                                        .split("\n")
                                        .map((x) => x.trim())
                                        .filter(Boolean),
                                    })
                                  }
                                  className="min-h-[90px] resize-none"
                                  placeholder="Kein zusätzlicher Kontext nötig."
                                />
                              </div>

                              <div className="space-y-2">
                                <Label className="text-sm">Relevante Studienbrief‑Kapitel</Label>
                                {ch.relevanteStudienbriefKapitel?.length ? (
                                  <ul className="text-sm text-muted-foreground list-disc pl-5 space-y-1">
                                    {ch.relevanteStudienbriefKapitel.map((k, idx) => (
                                      <li key={`${k.nummer}-${idx}`}>
                                        <span className="font-mono">{k.nummer}</span> {k.titel}{" "}
                                        <span className="text-xs">[{k.label}]</span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <p className="text-sm text-muted-foreground">—</p>
                                )}
                              </div>

                              <div className="flex items-center justify-between gap-3 pt-2 border-t">
                                <div className="flex items-center gap-2">
                                  <Checkbox
                                    id={`reviewed-${ch.id}`}
                                    checked={ch.reviewed}
                                    onCheckedChange={(v) => updateKapitel(ch.id, { reviewed: Boolean(v) })}
                                  />
                                  <Label htmlFor={`reviewed-${ch.id}`} className="text-sm cursor-pointer">
                                    Gelesen & geprüft
                                  </Label>
                                </div>
                                {hasError && (
                                  <span className="text-xs text-destructive">
                                    {hasDuplicate ? "Doppelte Nummer" : "Ungültige Nummer"}
                                  </span>
                                )}
                              </div>
                            </div>
                          </AccordionContent>
                        </AccordionItem>
                      )
                    })}
                  </Accordion>
                </div>
              </Card>

              <Card className="p-6">
                <div className="font-medium">Kurzbegründung</div>
                {output.kurzbegruendung?.length ? (
                  <ul className="mt-3 text-sm text-muted-foreground list-disc pl-5 space-y-1">
                    {output.kurzbegruendung.map((p, idx) => (
                      <li key={idx}>{p}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-muted-foreground">—</p>
                )}
              </Card>

              <Card className="p-6">
                <div className="font-medium">Verwendete Studienbrief‑Kapitel (unique)</div>
                {output.verwendeteStudienbriefKapitelUnique?.length ? (
                  <ul className="mt-3 text-sm text-muted-foreground grid gap-1 md:grid-cols-2">
                    {output.verwendeteStudienbriefKapitelUnique.map((k, idx) => (
                      <li key={`${k.nummer}-${idx}`}>
                        <span className="font-mono">{k.nummer}</span> {k.titel}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-muted-foreground">—</p>
                )}
              </Card>

              <Card className="p-6">
                <div className="font-medium">Annahmen</div>
                {output.annahmen?.length ? (
                  <ul className="mt-3 text-sm text-muted-foreground list-disc pl-5 space-y-1">
                    {output.annahmen.map((p, idx) => (
                      <li key={idx}>{p}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-muted-foreground">—</p>
                )}
              </Card>

              <Card className="p-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-medium">Gliederung übernehmen</div>
                    <p className="text-sm text-muted-foreground">
                      Erst wenn alles geprüft ist und keine Fehler vorliegen, werden Kapitel erstellt.
                    </p>
                  </div>
                  <Button
                    onClick={handleApply}
                    disabled={isApplying || saving || !allReviewed || hasBlockingErrors || total === 0}
                    className="min-w-[220px]"
                  >
                    {isApplying ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                    Kapitel erstellen
                  </Button>
                </div>
              </Card>
            </>
          )}
        </div>
      </div>

      <AlertDialog open={startOverConfirmOpen} onOpenChange={setStartOverConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Von vorne beginnen?</AlertDialogTitle>
            <AlertDialogDescription>
              Alle vorhandenen Entwürfe werden ins Archiv verschoben (nicht gelöscht). Du kannst sie später im Archiv
              wiederherstellen.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                await onStartOver()
                setStartOverConfirmOpen(false)
              }}
            >
              Entwürfe archivieren
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={archiveDialogOpen} onOpenChange={setArchiveDialogOpen}>
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle>Archiv</DialogTitle>
            <DialogDescription>Archivierte Entwürfe können wiederhergestellt werden.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 max-h-[55vh] overflow-y-auto">
            {archivedDrafts.length === 0 ? (
              <p className="text-sm text-muted-foreground">Keine archivierten Entwürfe.</p>
            ) : (
              archivedDrafts.map((d) => (
                <Card key={d.id} className="p-4 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{formatDraftLabel(d)}</div>
                    <div className="text-xs text-muted-foreground mt-1">Modell: {d.model || "—"}</div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={async () => {
                      await onRestoreDraft(d.id)
                    }}
                  >
                    Wiederherstellen
                  </Button>
                </Card>
              ))
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveDialogOpen(false)}>
              Schließen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
