"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { AlertTriangle, CheckCircle2, FileText, Loader2, Plus, Save, Trash2 } from "lucide-react"
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
import type { GliederungDraft, GliederungDraftOutput } from "@/app/types/gliederung"
import { cn } from "@/lib/utils"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

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
  onUpdateDraftOutput: (draftId: string, output: GliederungDraftOutput) => Promise<void>
  onRefineDraft: (draftId: string, message: string) => Promise<void>
  onApplyDraft: (draftId: string, output: GliederungDraftOutput) => Promise<void>
  isApplying: boolean
  isRefining: boolean
}

export function GliederungWorkspace({
  drafts,
  selectedDraftId,
  onSelectDraft,
  onOpenCreate,
  onUpdateDraftOutput,
  onRefineDraft,
  onApplyDraft,
  isApplying,
  isRefining,
}: GliederungWorkspaceProps) {
  const activeDrafts = useMemo(() => {
    return drafts
      .filter((d) => !d.archived)
      .slice()
      .sort((a, b) => (b.updatedAt?.valueOf?.() || 0) - (a.updatedAt?.valueOf?.() || 0))
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

  const [deleteKapitelId, setDeleteKapitelId] = useState<string | null>(null)

  const [output, setOutput] = useState<GliederungDraftOutput | null>(selectedDraft?.output ?? null)
  const [version, setVersion] = useState(0)
  const savedVersionRef = useRef(0)
  const attemptedVersionRef = useRef(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [refineMessage, setRefineMessage] = useState("")
  const [localRefining, setLocalRefining] = useState(false)
  const isDirty = version !== savedVersionRef.current

  useEffect(() => {
    setOutput(null)
    setVersion(0)
    savedVersionRef.current = 0
    attemptedVersionRef.current = 0
    setSaving(false)
    setSaveError(null)
    setRefineMessage("")
    setLocalRefining(false)
  }, [selectedDraft?.id])

  useEffect(() => {
    if (!selectedDraft?.output) return
    if (isDirty) return
    setOutput(selectedDraft.output)
  }, [isDirty, selectedDraft?.output])

  const validation = useMemo(() => validateKapitel(output), [output])

  const chapters = output?.kapitel ?? []
  const total = chapters.length
  const reviewedCount = chapters.filter((c) => c.reviewed).length
  const reviewProgress = total > 0 ? Math.round((reviewedCount / total) * 100) : 0

  const hasStructuralBlockingErrors = validation.invalidIds.size > 0 || validation.tooDeepIds.size > 0
  const hasDuplicateWarnings = validation.duplicateIds.size > 0
  const hasBlockingErrors = hasStructuralBlockingErrors
  const allReviewed = total > 0 && reviewedCount === total

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

  const deleteKapitel = (id: string) => {
    setOutput((prev) => {
      if (!prev) return prev
      return { ...prev, kapitel: prev.kapitel.filter((ch) => ch.id !== id) }
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
    if (isApplying || saving || isRefining || localRefining) return
    if (!allReviewed || hasBlockingErrors) return
    if (isDirty) {
      await handleSaveNow()
      if (version !== savedVersionRef.current) return
    }
    await onApplyDraft(selectedDraft.id, output)
  }

  const handleRefine = async () => {
    if (!selectedDraft || !output) return
    const msg = refineMessage.trim()
    if (!msg) return
    if (localRefining || isRefining) return
    if (isApplying || saving) return

    if (isDirty) {
      await handleSaveNow()
      if (version !== savedVersionRef.current) return
    }

    setLocalRefining(true)
    try {
      await onRefineDraft(selectedDraft.id, msg)
      setRefineMessage("")
    } finally {
      setLocalRefining(false)
    }
  }

  const header = (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <FileText className="h-5 w-5 text-primary" />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-semibold leading-tight">Gliederung (Entwurf)</h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-prose">
            Erstelle einen Entwurf, prüfe ihn sorgfältig und übernimm ihn erst danach als Kapitel.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        <Button variant="outline" size="sm" onClick={onOpenCreate} className="w-full sm:w-auto">
          <Plus className="h-4 w-4" />
          Neuer Entwurf
        </Button>
      </div>
    </div>
  )

  if (activeDrafts.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="max-w-2xl w-full">
          <Card className="p-8">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
                <FileText className="h-6 w-6 text-primary" />
              </div>
              <div className="min-w-0">
                <h2 className="text-2xl font-semibold leading-tight">Gliederung erstellen</h2>
                <p className="text-sm text-muted-foreground mt-2 max-w-prose">
                  Dieses Projekt hat noch keine Kapitel. Erstelle einen KI‑Entwurf und prüfe jeden Punkt sorgfältig,
                  bevor du ihn übernimmst.
                </p>
              </div>
            </div>

            <div className="mt-6 rounded-xl border bg-muted/20 p-4">
              <div className="text-sm font-medium">So funktioniert’s</div>
              <ol className="mt-3 grid gap-3 sm:grid-cols-3">
                <li className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-semibold shrink-0">
                    1
                  </div>
                  <div className="text-sm text-muted-foreground">
                    <span className="text-foreground font-medium">Entwurf erstellen</span>
                    <div className="text-xs text-muted-foreground mt-1">Aufgabenstellung eingeben und Modell wählen.</div>
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-semibold shrink-0">
                    2
                  </div>
                  <div className="text-sm text-muted-foreground">
                    <span className="text-foreground font-medium">Prüfen & bearbeiten</span>
                    <div className="text-xs text-muted-foreground mt-1">Nummern, Titel und Anweisungen anpassen.</div>
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-semibold shrink-0">
                    3
                  </div>
                  <div className="text-sm text-muted-foreground">
                    <span className="text-foreground font-medium">Übernehmen</span>
                    <div className="text-xs text-muted-foreground mt-1">Erst danach werden Kapitel erstellt.</div>
                  </div>
                </li>
              </ol>
            </div>

            <div className="mt-6">
              <Button onClick={onOpenCreate} className="w-full h-11 text-base">
                Gliederung erstellen
              </Button>
              <p className="text-xs text-muted-foreground mt-3">
                Hinweis: Du musst jedes Kapitel als „Gelesen & geprüft“ markieren, bevor du übernehmen kannst.
              </p>
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
                  <Label className="text-sm font-medium">Entwurf</Label>
                  <Select value={selectedDraft?.id || activeDrafts[0]?.id} onValueChange={(val) => onSelectDraft(val)}>
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
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-2"
                      onClick={handleSaveNow}
                      disabled={saving || !isDirty}
                    >
                      <Save className="h-4 w-4 mr-2" />
                      Speichern
                    </Button>
                  )}
                  {saveError && <p className="text-xs text-destructive mt-2">{saveError}</p>}
                </div>
              </div>
            )}
          </Card>

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
              {(hasBlockingErrors ||
                hasDuplicateWarnings ||
                validation.jumpWarnings.length > 0 ||
                validation.missingParentWarnings.length > 0) && (
                <Card
                  className={cn(
                    "p-4",
                    hasStructuralBlockingErrors ? "border-destructive/40" : "border-yellow-500/30"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <AlertTriangle
                      className={cn(
                        "h-5 w-5 mt-0.5",
                        hasStructuralBlockingErrors ? "text-destructive" : "text-yellow-600"
                      )}
                    />
                    <div className="space-y-2">
                      <div className="font-medium">
                        {hasStructuralBlockingErrors ? "Bitte Fehler beheben" : "Hinweise zur Nummerierung"}
                      </div>
                      {validation.duplicateIds.size > 0 && (
                        <p className="text-sm text-muted-foreground">
                          Hinweis: Es gibt doppelte Kapitelnummern. Du kannst trotzdem fortfahren.
                        </p>
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
                      const isDuplicateOnly = hasDuplicate && !hasInvalid
                      return (
                        <AccordionItem key={ch.id} value={ch.id}>
                          <AccordionTrigger className="hover:no-underline">
                            <div className="flex items-center justify-between gap-3 w-full">
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span
                                    className={cn(
                                      "font-mono text-xs text-muted-foreground",
                                      hasInvalid && "text-destructive",
                                      isDuplicateOnly && "text-yellow-700"
                                    )}
                                  >
                                    {ch.nummer?.trim() || "—"}
                                  </span>
                                  <span
                                    className={cn(
                                      "text-sm font-medium truncate",
                                      hasInvalid && "text-destructive",
                                      isDuplicateOnly && "text-yellow-800"
                                    )}
                                  >
                                    {ch.titel?.trim() || "Ohne Titel"}
                                  </span>
                                </div>
                                <div className="text-xs text-muted-foreground mt-0.5">
                                  {ch.seitenumfang?.trim() ? `Seiten: ${ch.seitenumfang.trim()}` : "—"}
                                </div>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                {hasInvalid && (
                                  <Badge variant="outline" className="border-destructive/40 text-destructive">
                                    Fehler
                                  </Badge>
                                )}
                                {isDuplicateOnly && (
                                  <Badge variant="outline" className="border-yellow-500/40 text-yellow-800">
                                    Prüfen
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
                                    className={cn(hasInvalid && "border-destructive", isDuplicateOnly && "border-yellow-500")}
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
                                <div className="flex items-center gap-2">
                                  {hasError && (
                                    <span
                                      className={cn(
                                        "text-xs",
                                        hasInvalid ? "text-destructive" : hasDuplicate ? "text-yellow-800" : "text-muted-foreground"
                                      )}
                                    >
                                      {hasInvalid ? "Ungültige Nummer" : hasDuplicate ? "Doppelte Nummer" : ""}
                                    </span>
                                  )}
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setDeleteKapitelId(ch.id)}
                                    disabled={saving || isApplying}
                                    className="border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                    Löschen
                                  </Button>
                                </div>
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
                <div className="font-medium">Änderungen anfordern</div>
                <p className="text-sm text-muted-foreground mt-1">
                  Beschreibe, was geändert werden soll. Die KI erstellt eine neue Version dieses Entwurfs – danach musst du
                  erneut prüfen.
                </p>
                <div className="mt-4 space-y-3">
                  <Textarea
                    value={refineMessage}
                    onChange={(e) => setRefineMessage(e.target.value)}
                    placeholder="z.B. Kapitel 2 und 3 vertauschen; Kapitel 3.2 kürzen; neue Überschrift für 1.2…"
                    className="min-h-[120px] resize-none"
                    disabled={saving || isApplying || isRefining || localRefining}
                  />
                  <div className="flex items-center justify-end gap-3">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleRefine}
                      disabled={
                        saving ||
                        isApplying ||
                        isRefining ||
                        localRefining ||
                        refineMessage.trim().length === 0 ||
                        !selectedDraft
                      }
                      className="min-w-[220px]"
                    >
                      {isRefining || localRefining ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                      Änderungen anfordern
                    </Button>
                  </div>
                </div>
              </Card>

              <Card className="p-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-medium">Gliederung übernehmen</div>
                    <p className="text-sm text-muted-foreground">
                      Erst wenn alles geprüft ist und keine blockierenden Fehler vorliegen, werden Kapitel erstellt.
                    </p>
                  </div>
                  {(() => {
                    const disabled =
                      isApplying || saving || isRefining || localRefining || !allReviewed || hasBlockingErrors || total === 0
                    const reasons: string[] = []
                    if (total === 0) reasons.push("Füge mindestens ein Kapitel hinzu.")
                    if (!allReviewed) reasons.push(`Markiere alle Kapitel als „Gelesen & geprüft“ (${reviewedCount}/${total}).`)
                    if (hasBlockingErrors) reasons.push("Behebe ungültige Nummern (Format 1 / 1.1 / 1.1.1) und max. Ebene 3.")
                    if (saving) reasons.push("Warte, bis der Entwurf gespeichert ist.")
                    if (isRefining || localRefining) reasons.push("Warte, bis die KI‑Änderungen fertig sind.")
                    if (isApplying) reasons.push("Kapitel werden gerade erstellt.")

                    return (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span tabIndex={disabled ? 0 : -1} className="inline-flex">
                            <Button onClick={handleApply} disabled={disabled} className="min-w-[220px]">
                              {isApplying ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                              Kapitel erstellen
                            </Button>
                          </span>
                        </TooltipTrigger>
                        {disabled && reasons.length > 0 ? (
                          <TooltipContent side="top" sideOffset={8} className="max-w-[360px]">
                            <div className="space-y-1">
                              <div className="font-medium">Noch nicht möglich</div>
                              <ul className="list-disc pl-4 space-y-0.5">
                                {reasons.map((r) => (
                                  <li key={r}>{r}</li>
                                ))}
                              </ul>
                            </div>
                          </TooltipContent>
                        ) : null}
                      </Tooltip>
                    )
                  })()}
                </div>
              </Card>
            </>
          )}
        </div>
      </div>

      <AlertDialog open={!!deleteKapitelId} onOpenChange={(open) => !open && setDeleteKapitelId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Kapitel löschen?</AlertDialogTitle>
            <AlertDialogDescription>
              Dieses Kapitel wird aus dem Entwurf entfernt. Das kann nicht automatisch rückgängig gemacht werden (du kannst
              aber jederzeit einen neuen Entwurf erstellen).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!deleteKapitelId) return
                deleteKapitel(deleteKapitelId)
                setDeleteKapitelId(null)
              }}
            >
              Löschen
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
