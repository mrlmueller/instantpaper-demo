"use client";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
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
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertCircle,
  Coins,
  Scissors,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import type { Kapitel, Quelle, Run } from "@/app/types/ui";
import { getSummaries, type SummaryResult } from "@/app/actions/kapitels";

interface KapitelWorkspaceProps {
  kapitel: Kapitel;
  assignedQuellen: Quelle[];
  runs: Run[];
  selectedRun: Run | undefined;
  allKapitels: Kapitel[];
  onSelectRun: (id: string) => void;
  onLoadAllRuns: () => void;
  allRunsLoaded: boolean;
  onOpenTextViewer: (content: { title: string; text: string }) => void;
  onOpenProcessing: () => void;
  onCombineTexts: () => void;
  onToggleQuellenPanel: () => void;
  onOpenShorten: () => void;
  onOpenLesefluss: () => void;
}

export function KapitelWorkspace({
  kapitel,
  assignedQuellen,
  runs,
  selectedRun,
  allKapitels,
  onSelectRun,
  onLoadAllRuns,
  allRunsLoaded,
  onOpenTextViewer,
  onOpenProcessing,
  onCombineTexts,
  onToggleQuellenPanel,
  onOpenShorten,
  onOpenLesefluss,
}: KapitelWorkspaceProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [themaExpanded, setThemaExpanded] = useState(false);
  const [intermediateGroupsExpanded, setIntermediateGroupsExpanded] =
    useState(false);
  const [contextSummariesExpanded, setContextSummariesExpanded] =
    useState(false);
  const [explanationExpanded, setExplanationExpanded] = useState(false);
  const [summaries, setSummaries] = useState<SummaryResult[]>([]);
  const [summariesLoading, setSummariesLoading] = useState(false);

  const hasContent =
    selectedRun?.combinedText && selectedRun.combinedText.length > 0;
  const hasQuellenErgebnisse =
    selectedRun?.quellenErgebnisse && selectedRun.quellenErgebnisse.length > 0;

  // Fetch summaries when selectedRun changes and has shortened text
  useEffect(() => {
    if (selectedRun?.shortenedText) {
      setSummariesLoading(true);
      getSummaries(kapitel.id, selectedRun.id)
        .then((fetchedSummaries) => {
          setSummaries(fetchedSummaries);
          setSummariesLoading(false);
        })
        .catch((error) => {
          console.error("Error fetching summaries:", error);
          setSummaries([]);
          setSummariesLoading(false);
        });
    } else {
      setSummaries([]);
    }
  }, [selectedRun?.id, selectedRun?.shortenedText, kapitel.id]);

  const handleCopy = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Calculate total cost including summaries
  const summariesCost = summaries.reduce(
    (sum, summary) => sum + summary.cost,
    0
  );
  const totalCost = selectedRun
    ? selectedRun.quellenCost +
      selectedRun.combinedCost +
      (selectedRun.shortenedCost || 0) +
      summariesCost
    : 0;

  const formatCost = (cents: number) => {
    const euros = cents / 100;
    return `${euros.toFixed(2)} €`;
  };

  const themaIsLong = selectedRun?.thema && selectedRun.thema.length > 80;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto py-12 px-8">
        {/* Kapitel Header - Added nummer prefix */}
        <div className="mb-8">
          <h1 className="text-3xl font-semibold text-foreground mb-2 text-balance leading-tight">
            <span className="text-muted-foreground/60 mr-2">
              {kapitel.nummer}
            </span>
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
          <Button
            onClick={onOpenProcessing}
            className="bg-primary text-primary-foreground"
          >
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
          {hasContent && selectedRun?.shortenedText && (
            <Button variant="outline" onClick={onOpenLesefluss}>
              <BookOpen className="h-4 w-4 mr-2" />
              Lese Fluss verbessern
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
                <Select
                  value={selectedRun?.id || ""}
                  onValueChange={(value) => {
                    if (value === "load_all") {
                      onLoadAllRuns();
                      return;
                    }
                    onSelectRun(value);
                  }}
                >
                  <SelectTrigger className="w-[200px]">
                    <SelectValue placeholder="Run auswählen" />
                  </SelectTrigger>
                  <SelectContent>
                    {runs.map((run, index) => (
                      <SelectItem key={run.id} value={run.id}>
                        {`Run ${run.index ?? runs.length - index}`} -{" "}
                        {run.timestamp.toLocaleDateString("de-DE")}
                      </SelectItem>
                    ))}
                    {!allRunsLoaded && (
                      <SelectItem value="load_all">Alle Runs laden</SelectItem>
                    )}
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
                <h2 className="text-lg font-medium text-foreground">
                  Kombinierter Text
                </h2>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      handleCopy(selectedRun!.combinedText, "combined")
                    }
                  >
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

        {/* Explanation Card */}
        {selectedRun?.shortenedText && selectedRun.explanation && (
          <Card className="mb-4 bg-blue-50/50 border-blue-200/70">
            <Collapsible
              open={explanationExpanded}
              onOpenChange={setExplanationExpanded}
            >
              <div className="p-6">
                <CollapsibleTrigger asChild>
                  <button className="flex items-center justify-between w-full group">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="h-5 w-5 text-blue-600" />
                      <h3 className="text-base font-medium text-foreground">
                        Bearbeitungsdetails
                      </h3>
                    </div>
                    {explanationExpanded ? (
                      <ChevronUp className="h-5 w-5 text-muted-foreground group-hover:text-foreground transition-colors" />
                    ) : (
                      <ChevronDown className="h-5 w-5 text-muted-foreground group-hover:text-foreground transition-colors" />
                    )}
                  </button>
                </CollapsibleTrigger>

                <CollapsibleContent className="mt-4 space-y-4">
                  {selectedRun.explanation.lengthDecision && (
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-medium text-foreground">
                          📝 Längenentscheidung:
                        </span>
                      </div>
                      <p className="text-sm text-foreground/80 leading-relaxed">
                        {selectedRun.explanation.lengthDecision}
                      </p>
                    </div>
                  )}

                  {selectedRun.explanation.omittedTopics &&
                    selectedRun.explanation.omittedTopics.length > 0 && (
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-sm font-medium text-foreground">
                            ❌ Weggelassene Themen:
                          </span>
                        </div>
                        <ul className="text-sm text-foreground/80 list-disc pl-5 space-y-1">
                          {selectedRun.explanation.omittedTopics.map(
                            (topic, i) => (
                              <li key={i}>{topic}</li>
                            )
                          )}
                        </ul>
                      </div>
                    )}

                  {selectedRun.explanation.preservedFocus &&
                    selectedRun.explanation.preservedFocus.length > 0 && (
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-sm font-medium text-foreground">
                            ✓ Beibehaltener Fokus:
                          </span>
                        </div>
                        <ul className="text-sm text-foreground/80 list-disc pl-5 space-y-1">
                          {selectedRun.explanation.preservedFocus.map(
                            (point, i) => (
                              <li key={i}>{point}</li>
                            )
                          )}
                        </ul>
                      </div>
                    )}

                  {selectedRun.explanation.compressionNotes && (
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-medium text-foreground">
                          💡 Zusätzliche Notizen:
                        </span>
                      </div>
                      <p className="text-sm text-foreground/80 leading-relaxed">
                        {selectedRun.explanation.compressionNotes}
                      </p>
                    </div>
                  )}

                  {selectedRun.shortenedOriginalLength &&
                    selectedRun.shortenedLength && (
                      <div className="pt-2 border-t border-border">
                        <span className="text-sm text-muted-foreground">
                          📊 Kompression: {selectedRun.shortenedOriginalLength}{" "}
                          → {selectedRun.shortenedLength} Wörter (
                          {(
                            (1 -
                              selectedRun.shortenedLength /
                                selectedRun.shortenedOriginalLength) *
                            100
                          ).toFixed(0)}
                          % Reduktion)
                        </span>
                      </div>
                    )}
                </CollapsibleContent>
              </div>
            </Collapsible>
          </Card>
        )}

        {/* Shortened Text */}
        {selectedRun?.shortenedText && (
          <>
            <Card className="mb-8 bg-card border-border shadow-sm">
              <div className="p-8">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-3">
                    <h2 className="text-lg font-medium text-foreground">
                      Gekürzter Text
                    </h2>
                    {selectedRun.shortenedCost && (
                      <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/50 rounded">
                        {formatCost(selectedRun.shortenedCost)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        handleCopy(selectedRun.shortenedText!, "shortened")
                      }
                    >
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

            {/* Context Summaries */}
            {summaries.length > 0 && (
              <Card className="mb-8 bg-card border-border shadow-sm">
                <Collapsible
                  open={contextSummariesExpanded}
                  onOpenChange={setContextSummariesExpanded}
                >
                  <div className="p-6">
                    <CollapsibleTrigger asChild>
                      <button className="flex items-center justify-between w-full group">
                        <div className="flex items-center gap-2">
                          <BookOpen className="h-5 w-5 text-muted-foreground" />
                          <h3 className="text-base font-medium text-foreground">
                            Verwendeter Kontext
                          </h3>
                          <span className="text-sm text-muted-foreground">
                            ({summaries.length} Kapitel)
                          </span>
                          {summariesCost > 0 && (
                            <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/50 rounded ml-2">
                              {formatCost(summariesCost)}
                            </span>
                          )}
                        </div>
                        {contextSummariesExpanded ? (
                          <ChevronUp className="h-5 w-5 text-muted-foreground group-hover:text-foreground transition-colors" />
                        ) : (
                          <ChevronDown className="h-5 w-5 text-muted-foreground group-hover:text-foreground transition-colors" />
                        )}
                      </button>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="mt-6 space-y-4">
                      {summaries.map((summary) => {
                        const sourceKapitel = allKapitels.find(
                          (k) => k.id === summary.sourceKapitelId
                        );
                        const reductionPercent =
                          summary.originalLength > 0
                            ? (
                                ((summary.originalLength -
                                  summary.summaryLength) /
                                  summary.originalLength) *
                                100
                              ).toFixed(0)
                            : 0;

                        return (
                          <div
                            key={summary.id}
                            className="border border-border rounded-lg p-4 bg-muted/30"
                          >
                            <div className="flex items-start justify-between mb-3">
                              <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="text-sm font-medium text-foreground">
                                    {sourceKapitel?.nummer || "?"}{" "}
                                    {sourceKapitel?.title ||
                                      "Unbekanntes Kapitel"}
                                  </span>
                                </div>
                                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                                  <span>
                                    {summary.originalLength} →{" "}
                                    {summary.summaryLength} Wörter
                                  </span>
                                  <span className="text-primary">
                                    −{reductionPercent}%
                                  </span>
                                  {summary.cost > 0 && (
                                    <span>{formatCost(summary.cost)}</span>
                                  )}
                                </div>
                              </div>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() =>
                                  onOpenTextViewer({
                                    title: `Zusammenfassung: ${sourceKapitel?.nummer} ${sourceKapitel?.title}`,
                                    text: summary.summaryContent,
                                  })
                                }
                              >
                                <Maximize2 className="h-4 w-4" />
                              </Button>
                            </div>
                            <div className="text-sm text-foreground/80 leading-relaxed whitespace-pre-wrap line-clamp-3">
                              {summary.summaryContent}
                            </div>
                          </div>
                        );
                      })}
                    </CollapsibleContent>
                  </div>
                </Collapsible>
              </Card>
            )}
          </>
        )}

        {/* Lesefluss Text */}
        {selectedRun?.leseflussText && (
          <>
            {/* Explanation Card */}
            {selectedRun.leseflussExplanation && (
              <Card className="mb-4 bg-green-50/50 border-green-200/70">
                <div className="p-6">
                  <div className="flex items-center gap-2 mb-3">
                    <CheckCircle className="h-5 w-5 text-green-600" />
                    <h3 className="text-base font-medium text-foreground">
                      Was wurde verändert
                    </h3>
                  </div>
                  <p className="text-sm text-foreground/80 leading-relaxed">
                    {selectedRun.leseflussExplanation}
                  </p>
                </div>
              </Card>
            )}

            {/* Lesefluss Text Card */}
            <Card className="mb-8 bg-card border-border shadow-sm">
              <div className="p-8">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-3">
                    <h2 className="text-lg font-medium text-foreground">
                      Text mit verbessertem Lesefluss
                    </h2>
                    {selectedRun.leseflussLength &&
                      selectedRun.leseflussOriginalLength && (
                        <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/50 rounded">
                          {selectedRun.leseflussOriginalLength} →{" "}
                          {selectedRun.leseflussLength} Wörter
                        </span>
                      )}
                    {selectedRun.leseflussCost && (
                      <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/50 rounded">
                        {formatCost(selectedRun.leseflussCost)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        handleCopy(selectedRun.leseflussText!, "lesefluss")
                      }
                    >
                      {copiedId === "lesefluss" ? (
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
                          title: `${kapitel.nummer} ${kapitel.title} - Lese Fluss`,
                          text: selectedRun.leseflussText!,
                        })
                      }
                    >
                      <Maximize2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="prose prose-sm max-w-none">
                  <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-[12]">
                    {selectedRun.leseflussText}
                  </div>
                </div>
                {selectedRun.leseflussText.split("\n").length > 12 && (
                  <Button
                    variant="link"
                    className="mt-4 p-0 h-auto text-primary"
                    onClick={() =>
                      onOpenTextViewer({
                        title: `${kapitel.nummer} ${kapitel.title} - Lese Fluss`,
                        text: selectedRun.leseflussText!,
                      })
                    }
                  >
                    Vollständigen Text anzeigen
                  </Button>
                )}
              </div>
            </Card>
          </>
        )}

        {/* Intermediate Groups - Collapsible section */}
        {hasContent &&
          selectedRun?.intermediateGroups &&
          selectedRun.intermediateGroups.length > 0 && (
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
                                  onClick={() =>
                                    handleCopy(
                                      group.combinedContent,
                                      `group-${group.id}`
                                    )
                                  }
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
              <h3 className="text-base font-medium text-foreground mb-2">
                Einzeltexte bereit zum Kombinieren
              </h3>
              <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
                Die Einzeltexte wurden generiert. Klicke auf den Button, um sie
                zu einem zusammenhängenden Kapiteltext zu kombinieren.
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
              <h3 className="text-base font-medium text-foreground mb-2">
                Noch kein Text generiert
              </h3>
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
                <span className="font-medium">Überschrift:</span>{" "}
                {selectedRun.ueberschrift}
              </div>
            </div>
            {selectedRun.thema && (
              <div className="mt-3 text-sm">
                <div className="flex items-start gap-2">
                  <span className="font-medium text-muted-foreground shrink-0">
                    Anweisung:
                  </span>
                  <div className="flex-1 min-w-0">
                    {themaIsLong && !themaExpanded ? (
                      <div>
                        <span className="text-muted-foreground">
                          {selectedRun.thema.slice(0, 80)}...
                        </span>
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
                        <span className="text-muted-foreground">
                          {selectedRun.thema}
                        </span>
                        <button
                          onClick={() => setThemaExpanded(false)}
                          className="ml-2 text-primary hover:underline inline-flex items-center gap-1"
                        >
                          Weniger anzeigen
                          <ChevronUp className="h-3 w-3" />
                        </button>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">
                        {selectedRun.thema}
                      </span>
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
              <h2 className="text-base font-medium text-foreground">
                Ergebnisse pro Quelle
              </h2>
              <span className="text-sm text-muted-foreground">
                {selectedRun!.quellenErgebnisse.length} Texte
              </span>
            </div>
            <div className="space-y-3">
              {selectedRun!.quellenErgebnisse.map((ergebnis) => (
                <Card
                  key={ergebnis.id}
                  className={cn(
                    "bg-card border-border transition-colors",
                    ergebnis.status === "success" && "hover:border-primary/30",
                    ergebnis.status === "waiting" && "bg-muted/20",
                    ergebnis.status === "no-content" &&
                      "bg-amber-50/50 border-amber-200/50"
                  )}
                >
                  <div className="p-5">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-semibold text-foreground truncate">
                          {ergebnis.quelleName}
                        </h3>
                      </div>
                      {ergebnis.status === "success" && (
                        <div className="flex items-center gap-1 shrink-0 ml-3">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() =>
                              handleCopy(ergebnis.text, ergebnis.id)
                            }
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
                          <p className="text-sm font-medium">
                            Keine verwendbaren Inhalte
                          </p>
                          <p className="text-xs text-amber-600 mt-1">
                            Diese Quelle enthält keine relevanten Informationen
                            für das angegebene Thema.
                          </p>
                        </div>
                      </div>
                    ) : (
                      <div className="text-sm text-foreground/80 leading-relaxed line-clamp-4">
                        {ergebnis.text}
                      </div>
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
              Füge Quellen zu diesem Kapitel hinzu, um mit der Verarbeitung zu
              beginnen.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
