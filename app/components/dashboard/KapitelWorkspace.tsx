"use client"

import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible"
import {
  Play,
  FileText,
  Calendar,
  Copy,
  Maximize2,
  BookOpen,
  History,
  Layers,
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertCircle,
  Coins,
  Scissors,
} from "lucide-react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useState } from "react"
import { cn } from "@/lib/utils"
import type { Kapitel, Quelle, Run } from "@/app/types/ui"

interface KapitelWorkspaceProps {
  kapitel: Kapitel
  assignedQuellen: Quelle[]
  runs: Run[]
  selectedRun: Run | undefined
  onSelectRun: (id: string) => void
  onOpenTextViewer: (content: { title: string; text: string }) => void
  onOpenProcessing: () => void
  onCombineTexts: () => void
  onToggleQuellenPanel: () => void
  onOpenShorten: () => void
}

export function KapitelWorkspace({
  kapitel,
  assignedQuellen,
  runs,
  selectedRun,
  onSelectRun,
  onOpenTextViewer,
  onOpenProcessing,
  onCombineTexts,
  onToggleQuellenPanel,
  onOpenShorten,
}: KapitelWorkspaceProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [themaExpanded, setThemaExpanded] = useState(false)
  const [intermediateGroupsExpanded, setIntermediateGroupsExpanded] = useState(false)

  const hasContent = selectedRun?.combinedText && selectedRun.combinedText.length > 0
  const hasQuellenErgebnisse = selectedRun?.quellenErgebnisse && selectedRun.quellenErgebnisse.length > 0

  const handleCopy = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const totalCost = selectedRun ? selectedRun.quellenCost + selectedRun.combinedCost : 0

  const formatCost = (cents: number) => {
    const euros = cents / 100
    return `${euros.toFixed(2)} €`
  }

  const themaIsLong = selectedRun?.thema && selectedRun.thema.length > 80

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto py-12 px-8">
        {/* Kapitel Header - Added nummer prefix */}
        <div className="mb-8">
          <h1 className="text-3xl font-semibold text-foreground mb-2 text-balance leading-tight">
            <span className="text-muted-foreground/60 mr-2">{kapitel.nummer}</span>
            {kapitel.title}
          </h1>
          <div className="flex items-center gap-4 text-sm text-muted-foreground flex-wrap">
            <button
              onClick={onToggleQuellenPanel}
              className="flex items-center gap-1.5 hover:text-foreground transition-colors"
            >
              <FileText className="h-4 w-4" />
              <span>{assignedQuellen.length} Quellen zugewiesen</span>
            </button>
            {selectedRun && (
              <>
                <div className="flex items-center gap-1.5">
                  <Calendar className="h-4 w-4" />
                  <span>
                    Verarbeitet:{" "}
                    {selectedRun.timestamp.toLocaleDateString("de-DE", {
                      day: "2-digit",
                      month: "2-digit",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Coins className="h-4 w-4" />
                  <span>Kosten: {formatCost(totalCost)}</span>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Action Bar */}
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          <Button onClick={onOpenProcessing} className="bg-primary text-primary-foreground">
            <Play className="h-4 w-4 mr-2" />
            Kapitel verarbeiten
          </Button>
          <Button variant="outline" onClick={onToggleQuellenPanel}>
            <BookOpen className="h-4 w-4 mr-2" />
            Quellen verwalten
          </Button>
          {hasContent && (
            <Button variant="outline" onClick={onOpenShorten}>
              <Scissors className="h-4 w-4 mr-2" />
              Text kürzen
            </Button>
          )}

          <div className="flex items-center gap-3 ml-auto">
            {selectedRun && (
              <div className="flex items-center gap-1.5 text-sm text-muted-foreground px-3 py-1.5 bg-muted/50 rounded-md">
                <Coins className="h-4 w-4" />
                <span>{formatCost(totalCost)}</span>
              </div>
            )}

            {runs.length > 0 && (
              <div className="flex items-center gap-2">
                <History className="h-4 w-4 text-muted-foreground" />
                <Select value={selectedRun?.id || ""} onValueChange={onSelectRun}>
                  <SelectTrigger className="w-[200px]">
                    <SelectValue placeholder="Run auswählen" />
                  </SelectTrigger>
                  <SelectContent>
                    {runs.map((run, index) => (
                      <SelectItem key={run.id} value={run.id}>
                        {`Run ${run.index ?? runs.length - index}`} - {run.timestamp.toLocaleDateString("de-DE")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>

        {/* Combined Text - Removed individual cost badge */}
        {hasContent ? (
          <Card className="mb-8 bg-card border-border shadow-sm">
            <div className="p-8">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-medium text-foreground">Kombinierter Text</h2>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={() => handleCopy(selectedRun!.combinedText, "combined")}>
                    {copiedId === "combined" ? (
                      <Check className="h-4 w-4 text-primary" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      onOpenTextViewer({
                        title: `${kapitel.nummer} ${kapitel.title} - Kombinierter Text`,
                        text: selectedRun!.combinedText,
                      })
                    }
                  >
                    <Maximize2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="prose prose-sm max-w-none">
                <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-[12]">
                  {selectedRun!.combinedText}
                </div>
              </div>
              {selectedRun!.combinedText.split("\n").length > 12 && (
                <Button
                  variant="link"
                  className="mt-4 p-0 h-auto text-primary"
                  onClick={() =>
                    onOpenTextViewer({
                      title: `${kapitel.nummer} ${kapitel.title} - Kombinierter Text`,
                      text: selectedRun!.combinedText,
                    })
                  }
                >
                  Vollständigen Text anzeigen
                </Button>
              )}
            </div>
          </Card>
        ) : null}

        {/* Shortened Text */}
        {selectedRun?.shortenedText && (
          <Card className="mb-8 bg-card border-border shadow-sm">
            <div className="p-8">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <h2 className="text-lg font-medium text-foreground">Gekürzter Text</h2>
                  {selectedRun.shortenedCost && (
                    <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/50 rounded">
                      {formatCost(selectedRun.shortenedCost)}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={() => handleCopy(selectedRun.shortenedText!, "shortened")}>
                    {copiedId === "shortened" ? (
                      <Check className="h-4 w-4 text-primary" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      onOpenTextViewer({
                        title: `${kapitel.nummer} ${kapitel.title} - Gekürzter Text`,
                        text: selectedRun.shortenedText!,
                      })
                    }
                  >
                    <Maximize2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="prose prose-sm max-w-none">
                <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-[12]">
                  {selectedRun.shortenedText}
                </div>
              </div>
              {selectedRun.shortenedText.split("\n").length > 12 && (
                <Button
                  variant="link"
                  className="mt-4 p-0 h-auto text-primary"
                  onClick={() =>
                    onOpenTextViewer({
                      title: `${kapitel.nummer} ${kapitel.title} - Gekürzter Text`,
                      text: selectedRun.shortenedText!,
                    })
                  }
                >
                  Vollständigen Text anzeigen
                </Button>
              )}
            </div>
          </Card>
        )}

        {/* Intermediate Groups - Collapsible section */}
        {hasContent && selectedRun?.intermediateGroups && selectedRun.intermediateGroups.length > 0 && (
          <Card className="mb-8 bg-card border-border shadow-sm">
            <Collapsible
              open={intermediateGroupsExpanded}
              onOpenChange={setIntermediateGroupsExpanded}
            >
              <div className="p-6">
                <CollapsibleTrigger asChild>
                  <button className="flex items-center justify-between w-full group">
                    <div className="flex items-center gap-2">
                      <Layers className="h-5 w-5 text-muted-foreground" />
                      <h3 className="text-base font-medium text-foreground">
                        Zwischenergebnisse
                      </h3>
                      <span className="text-sm text-muted-foreground">
                        ({selectedRun.intermediateGroups.length} Gruppen)
                      </span>
                    </div>
                    {intermediateGroupsExpanded ? (
                      <ChevronUp className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors" />
                    )}
                  </button>
                </CollapsibleTrigger>

                <CollapsibleContent>
                  <div className="mt-4 space-y-3">
                    {selectedRun.intermediateGroups.map((group) => (
                      <Card
                        key={group.id}
                        className="bg-muted/20 border-border/50"
                      >
                        <div className="p-4">
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2">
                              <h4 className="text-sm font-semibold text-foreground">
                                Gruppe {group.groupNumber}
                              </h4>
                              <span className="text-xs text-muted-foreground">
                                {group.sourceQuelleIds.length} Quellen
                              </span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() => handleCopy(group.combinedContent, `group-${group.id}`)}
                              >
                                {copiedId === `group-${group.id}` ? (
                                  <Check className="h-3.5 w-3.5 text-primary" />
                                ) : (
                                  <Copy className="h-3.5 w-3.5" />
                                )}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() =>
                                  onOpenTextViewer({
                                    title: `${kapitel.nummer} ${kapitel.title} - Gruppe ${group.groupNumber}`,
                                    text: group.combinedContent,
                                  })
                                }
                              >
                                <Maximize2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>
                          <div className="text-sm text-foreground/80 leading-relaxed line-clamp-3">
                            {group.combinedContent}
                          </div>
                        </div>
                      </Card>
                    ))}
                  </div>
                </CollapsibleContent>
              </div>
            </Collapsible>
          </Card>
        )}

        {hasQuellenErgebnisse && !hasContent ? (
          <Card className="mb-8 bg-accent/30 border-border border-dashed">
            <div className="p-8 text-center">
              <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
                <Layers className="h-6 w-6 text-primary" />
              </div>
              <h3 className="text-base font-medium text-foreground mb-2">Einzeltexte bereit zum Kombinieren</h3>
              <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
                Die Einzeltexte wurden generiert. Klicke auf den Button, um sie zu einem zusammenhängenden Kapiteltext
                zu kombinieren.
              </p>
              <Button onClick={onCombineTexts}>
                <Layers className="h-4 w-4 mr-2" />
                Texte kombinieren
              </Button>
            </div>
          </Card>
        ) : runs.length === 0 ? (
          <Card className="mb-8 bg-accent/30 border-border border-dashed">
            <div className="p-12 text-center">
              <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
                <Play className="h-6 w-6 text-primary" />
              </div>
              <h3 className="text-base font-medium text-foreground mb-2">Noch kein Text generiert</h3>
              <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
                {assignedQuellen.length === 0
                  ? "Füge zuerst Quellen zu diesem Kapitel hinzu, dann kannst du es verarbeiten."
                  : `Du hast ${assignedQuellen.length} Quellen zugewiesen. Verarbeite dieses Kapitel, um einen zusammenhängenden Text zu erstellen.`}
              </p>
              <Button
                onClick={onOpenProcessing}
                disabled={assignedQuellen.length === 0}
                className="bg-primary text-primary-foreground"
              >
                <Play className="h-4 w-4 mr-2" />
                Kapitel verarbeiten
              </Button>
            </div>
          </Card>
        ) : null}

        {/* Run Info */}
        {selectedRun && (
          <div className="mb-6 p-4 bg-muted/30 rounded-lg">
            <div className="flex items-start gap-6 text-sm text-muted-foreground">
              <div className="shrink-0">
                <span className="font-medium">Modell:</span> {selectedRun.model}
              </div>
              <div className="shrink-0">
                <span className="font-medium">Überschrift:</span> {selectedRun.ueberschrift}
              </div>
            </div>
            {selectedRun.thema && (
              <div className="mt-3 text-sm">
                <div className="flex items-start gap-2">
                  <span className="font-medium text-muted-foreground shrink-0">Anweisung:</span>
                  <div className="flex-1 min-w-0">
                    {themaIsLong && !themaExpanded ? (
                      <div>
                        <span className="text-muted-foreground">{selectedRun.thema.slice(0, 80)}...</span>
                        <button
                          onClick={() => setThemaExpanded(true)}
                          className="ml-2 text-primary hover:underline inline-flex items-center gap-1"
                        >
                          Mehr anzeigen
                          <ChevronDown className="h-3 w-3" />
                        </button>
                      </div>
                    ) : themaIsLong ? (
                      <div>
                        <span className="text-muted-foreground">{selectedRun.thema}</span>
                        <button
                          onClick={() => setThemaExpanded(false)}
                          className="ml-2 text-primary hover:underline inline-flex items-center gap-1"
                        >
                          Weniger anzeigen
                          <ChevronUp className="h-3 w-3" />
                        </button>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">{selectedRun.thema}</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Per-Quelle Ergebnisse - Removed individual cost badges */}
        {hasQuellenErgebnisse && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-medium text-foreground">Ergebnisse pro Quelle</h2>
              <span className="text-sm text-muted-foreground">{selectedRun!.quellenErgebnisse.length} Texte</span>
            </div>
            <div className="space-y-3">
              {selectedRun!.quellenErgebnisse.map((ergebnis) => (
                <Card
                  key={ergebnis.id}
                  className={cn(
                    "bg-card border-border transition-colors",
                    ergebnis.status === "success" && "hover:border-primary/30",
                    ergebnis.status === "waiting" && "bg-muted/20",
                    ergebnis.status === "no-content" && "bg-amber-50/50 border-amber-200/50",
                  )}
                >
                  <div className="p-5">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-semibold text-foreground truncate">{ergebnis.quelleName}</h3>
                      </div>
                      {ergebnis.status === "success" && (
                        <div className="flex items-center gap-1 shrink-0 ml-3">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() => handleCopy(ergebnis.text, ergebnis.id)}
                          >
                            {copiedId === ergebnis.id ? (
                              <Check className="h-3.5 w-3.5 text-primary" />
                            ) : (
                              <Copy className="h-3.5 w-3.5" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() =>
                              onOpenTextViewer({
                                title: ergebnis.quelleName,
                                text: ergebnis.text,
                              })
                            }
                          >
                            <Maximize2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      )}
                    </div>

                    {ergebnis.status === "waiting" ? (
                      <div className="flex items-center gap-3 py-4 text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span className="text-sm">Text wird generiert...</span>
                      </div>
                    ) : ergebnis.status === "no-content" ? (
                      <div className="flex items-start gap-3 py-3 text-amber-700">
                        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                        <div>
                          <p className="text-sm font-medium">Keine verwendbaren Inhalte</p>
                          <p className="text-xs text-amber-600 mt-1">
                            Diese Quelle enthält keine relevanten Informationen für das angegebene Thema.
                          </p>
                        </div>
                      </div>
                    ) : (
                      <div className="text-sm text-foreground/80 leading-relaxed line-clamp-4">{ergebnis.text}</div>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          </div>
        )}

        {runs.length === 0 && assignedQuellen.length === 0 && (
          <div className="mt-8 p-8 rounded-lg bg-muted/30 text-center">
            <p className="text-sm text-muted-foreground">
              Füge Quellen zu diesem Kapitel hinzu, um mit der Verarbeitung zu beginnen.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
