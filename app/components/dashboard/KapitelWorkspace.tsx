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
  Sparkles,
  Library,
  MessageSquareText,
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
import { ProcessingStepper } from "./ProcessingStepper";

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
  isCombining: boolean;
  onToggleQuellenPanel: () => void;
  onOpenShorten: () => void;
  onOpenLesefluss: () => void;
  onOpenCombinedRefinement: () => void;
  onOpenShortenedRefinement: () => void;
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
  isCombining,
  onToggleQuellenPanel,
  onOpenShorten,
  onOpenLesefluss,
  onOpenCombinedRefinement,
  onOpenShortenedRefinement,
}: KapitelWorkspaceProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [intermediateGroupsExpanded, setIntermediateGroupsExpanded] =
    useState(false);
  const [gekuerztSummariesExpanded, setGekuerztSummariesExpanded] =
    useState(false);
  const [verbessertSummariesExpanded, setVerbessertSummariesExpanded] =
    useState(false);
  const [showAllQuellen, setShowAllQuellen] = useState(false);
  const [summaries, setSummaries] = useState<SummaryResult[]>([]);
  const [summariesLoading, setSummariesLoading] = useState(false);

  const hasContent =
    selectedRun?.combinedText && selectedRun.combinedText.length > 0;
  const hasQuellenErgebnisse =
    selectedRun?.quellenErgebnisse && selectedRun.quellenErgebnisse.length > 0;
  const hasGekuerzt =
    selectedRun?.shortenedText && selectedRun.shortenedText.length > 0;
  const hasVerbessert =
    selectedRun?.leseflussText && selectedRun.leseflussText.length > 0;
  const hasIntermediateGroups =
    selectedRun?.intermediateGroups && selectedRun.intermediateGroups.length > 0;

  // Fetch summaries when selectedRun changes and has generated text (shortened or improved)
  useEffect(() => {
    if (selectedRun?.shortenedText || selectedRun?.leseflussText) {
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
  }, [selectedRun?.id, selectedRun?.shortenedText, selectedRun?.leseflussText, kapitel.id]);

  const handleCopy = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Calculate total cost including summaries and lesefluss
  const summariesCost = summaries.reduce(
    (sum, summary) => sum + summary.cost,
    0
  );
  const totalCost = selectedRun
    ? selectedRun.quellenCost +
      selectedRun.combinedCost +
      (selectedRun.combinedRefinementCost || 0) +
      (selectedRun.shortenedCost || 0) +
      (selectedRun.shortenedRefinementCost || 0) +
      (selectedRun.leseflussCost || 0) +
      summariesCost
    : 0;

  const formatCost = (cents: number) => {
    const euros = cents / 100;
    return `${euros.toFixed(2)} €`;
  };

  const themaIsLong = selectedRun?.thema && selectedRun.thema.length > 80;

  // Show first 5 quellen by default in header tags
  const MAX_VISIBLE_QUELLEN_HEADER = 5;
  const hasMoreQuellenHeader = assignedQuellen.length > MAX_VISIBLE_QUELLEN_HEADER;
  const visibleQuellen = showAllQuellen
    ? assignedQuellen
    : assignedQuellen.slice(0, MAX_VISIBLE_QUELLEN_HEADER);
  const hiddenCount = assignedQuellen.length - MAX_VISIBLE_QUELLEN_HEADER;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto py-12 px-8">
        {/* Kapitel Header with Quellen Tags */}
        <div className="mb-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                <span className="text-muted-foreground mr-2">{kapitel.nummer}</span>
                {kapitel.title}
              </h1>
              {assignedQuellen.length > 0 && (
                <div className="mt-3 flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-muted-foreground">Quellen:</span>
                  {visibleQuellen.map((quelle) => (
                    <span
                      key={quelle.id}
                      className="px-2 py-0.5 bg-primary/10 text-primary rounded text-xs font-medium"
                    >
                      {quelle.name.length > 25 ? `${quelle.name.slice(0, 25)}...` : quelle.name}
                    </span>
                  ))}
                  {hasMoreQuellenHeader && !showAllQuellen && (
                    <button
                      onClick={() => setShowAllQuellen(true)}
                      className="px-2 py-0.5 bg-muted text-muted-foreground rounded text-xs font-medium hover:bg-muted/80 transition-colors"
                    >
                      +{hiddenCount} weitere
                    </button>
                  )}
                  {showAllQuellen && hasMoreQuellenHeader && (
                    <button
                      onClick={() => setShowAllQuellen(false)}
                      className="px-2 py-0.5 bg-muted text-muted-foreground rounded text-xs font-medium hover:bg-muted/80 transition-colors"
                    >
                      weniger
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={onToggleQuellenPanel}>
                <Library className="h-4 w-4 mr-2" />
                Quellen
              </Button>
              <Button onClick={onOpenProcessing}>
                <Play className="h-4 w-4 mr-2" />
                Kapitel verarbeiten
              </Button>
            </div>
          </div>
        </div>

        {/* Run Selector & Cost Display */}
        {selectedRun && (
          <div className="flex items-center justify-between mb-4 gap-4">
            <Select value={selectedRun.id} onValueChange={onSelectRun}>
              <SelectTrigger className="w-[200px]">
                <SelectValue placeholder="Run auswählen" />
              </SelectTrigger>
              <SelectContent>
                {runs.map((run, index) => (
                  <SelectItem key={run.id} value={run.id}>
                    Run {runs.length - index}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">{selectedRun.model}</span>
              <span className="text-sm font-medium px-2.5 py-1 bg-muted rounded-md">
                Kosten: {formatCost(totalCost)}
              </span>
            </div>
          </div>
        )}

        {/* Processing Stepper */}
        {selectedRun && (
          <ProcessingStepper
            hasQuellen={!!hasQuellenErgebnisse}
            hasCombined={!!hasContent}
            hasGekuerzt={!!hasGekuerzt}
            hasVerbessert={!!hasVerbessert}
          />
        )}

        {/* Run Info Card */}
        {selectedRun && (
          <Card className="p-4 mb-6 bg-muted/20">
            <div className="space-y-2 text-sm">
              <div className="flex items-start gap-2">
                <span className="text-muted-foreground shrink-0 w-24">Überschrift:</span>
                <span className="text-foreground">{selectedRun.ueberschrift}</span>
              </div>
              {selectedRun.thema && (
                <div className="flex items-start gap-2">
                  <span className="text-muted-foreground shrink-0 w-24">Anweisung:</span>
                  <span className={cn("text-foreground", themaIsLong && "line-clamp-2")}>
                    {selectedRun.thema}
                  </span>
                </div>
              )}
            </div>
          </Card>
        )}

        {/* NEW ORDER: Verbessert → Gekürzt → Intermediate Groups → Kombiniert → Quellen */}

        {/* 1. Verbesserter Text (Lesefluss) - PRIMARY STYLING */}
        {hasVerbessert && (
          <>
            {/* Explanation Card */}
            {selectedRun.leseflussExplanation && (
              <Card className="mb-4 bg-green-50/50 dark:bg-green-950/20 border-green-200/70 dark:border-green-800/50">
                <div className="p-6">
                  <div className="flex items-center gap-2 mb-3">
                    <CheckCircle className="h-5 w-5 text-green-600 dark:text-green-500" />
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

            {/* Verbesserter Text Card */}
            <Card className="mb-8 bg-card border-border shadow-sm ring-2 ring-primary/20">
              <div className="p-8">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-3">
                    <h2 className="text-lg font-medium text-foreground">
                      Verbesserter Text
                    </h2>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        handleCopy(selectedRun.leseflussText!, "verbessert")
                      }
                    >
                      {copiedId === "verbessert" ? (
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
                          title: `${kapitel.nummer} ${kapitel.title} - Verbesserter Text`,
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
              </div>

              {/* Kontext-Zusammenfassungen for Verbesserter Text */}
              {summaries.length > 0 && (
                <div className="px-8 pb-8">
                  <div className="pt-6 border-t border-border/50">
                    <Collapsible
                      open={verbessertSummariesExpanded}
                      onOpenChange={setVerbessertSummariesExpanded}
                    >
                      <CollapsibleTrigger asChild>
                        <button className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors w-full justify-between group">
                          <span className="font-medium">
                            Kontext-Zusammenfassungen ({summaries.length})
                          </span>
                          <ChevronDown
                            className={cn(
                              "h-4 w-4 transition-transform",
                              verbessertSummariesExpanded && "rotate-180"
                            )}
                          />
                        </button>
                      </CollapsibleTrigger>
                      <CollapsibleContent className="mt-3 space-y-3">
                        {summaries.map((summary) => {
                          const sourceKapitel = allKapitels.find(
                            (k) => k.id === summary.sourceKapitelId
                          );

                          return (
                            <div
                              key={summary.id}
                              className="p-3 bg-muted/30 rounded-md"
                            >
                              <div className="flex items-center justify-between mb-2">
                                <h4 className="text-xs font-medium text-muted-foreground">
                                  <span className="mr-1">
                                    {sourceKapitel?.nummer || "?"}
                                  </span>
                                  {sourceKapitel?.title || "Unbekanntes Kapitel"}
                                </h4>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-6 w-6 p-0"
                                  onClick={() =>
                                    onOpenTextViewer({
                                      title: `Zusammenfassung: ${sourceKapitel?.nummer} ${sourceKapitel?.title}`,
                                      text: summary.summaryContent,
                                    })
                                  }
                                >
                                  <Maximize2 className="h-3 w-3" />
                                </Button>
                              </div>
                              <p className="text-xs text-foreground/70 leading-relaxed line-clamp-3">
                                {summary.summaryContent}
                              </p>
                            </div>
                          );
                        })}
                      </CollapsibleContent>
                    </Collapsible>
                  </div>
                </div>
              )}
            </Card>
          </>
        )}

        {/* 2. Gekürzter Text (Shortened) */}
        {hasGekuerzt && (
          <>
            <Card className="mb-8 bg-card border-border shadow-sm">
              <div className="p-8">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-3">
                    <h2 className="text-lg font-medium text-foreground">
                      Gekürzter Text
                    </h2>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={onOpenShortenedRefinement}
                    >
                      <MessageSquareText className="h-4 w-4 mr-2" />
                      Verfeinern
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={onOpenLesefluss}
                    >
                      <Sparkles className="h-4 w-4 mr-2" />
                      Lesefluss
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        handleCopy(selectedRun!.shortenedText!, "gekuerzt")
                      }
                    >
                      {copiedId === "gekuerzt" ? (
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
                          text: selectedRun!.shortenedText!,
                        })
                      }
                    >
                      <Maximize2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="prose prose-sm max-w-none">
                  <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-[12]">
                    {selectedRun!.shortenedText}
                  </div>
                </div>
                {selectedRun!.shortenedText!.split("\n").length > 12 && (
                  <Button
                    variant="link"
                    className="mt-4 p-0 h-auto text-primary"
                    onClick={() =>
                      onOpenTextViewer({
                        title: `${kapitel.nummer} ${kapitel.title} - Gekürzter Text`,
                        text: selectedRun!.shortenedText!,
                      })
                    }
                  >
                    Vollständigen Text anzeigen
                  </Button>
                )}
              </div>

              {/* Context Summaries for Gekürzt - Collapsible with preview */}
              {summaries.length > 0 && (
                <div className="px-8 pb-8">
                  <div className="pt-6 border-t border-border/50">
                    <Collapsible
                      open={gekuerztSummariesExpanded}
                      onOpenChange={setGekuerztSummariesExpanded}
                    >
                      <CollapsibleTrigger asChild>
                        <button className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors w-full justify-between group">
                          <span className="font-medium">
                            Kontext-Zusammenfassungen ({summaries.length})
                          </span>
                          <ChevronDown
                            className={cn(
                              "h-4 w-4 transition-transform",
                              gekuerztSummariesExpanded && "rotate-180"
                            )}
                          />
                        </button>
                      </CollapsibleTrigger>
                      <CollapsibleContent className="mt-3 space-y-3">
                        {summaries.map((summary) => {
                          const sourceKapitel = allKapitels.find(
                            (k) => k.id === summary.sourceKapitelId
                          );

                          return (
                            <div
                              key={summary.id}
                              className="p-3 bg-muted/30 rounded-md"
                            >
                              <div className="flex items-center justify-between mb-2">
                                <h4 className="text-xs font-medium text-muted-foreground">
                                  <span className="mr-1">
                                    {sourceKapitel?.nummer || "?"}
                                  </span>
                                  {sourceKapitel?.title || "Unbekanntes Kapitel"}
                                </h4>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-6 w-6 p-0"
                                  onClick={() =>
                                    onOpenTextViewer({
                                      title: `Zusammenfassung: ${sourceKapitel?.nummer} ${sourceKapitel?.title}`,
                                      text: summary.summaryContent,
                                    })
                                  }
                                >
                                  <Maximize2 className="h-3 w-3" />
                                </Button>
                              </div>
                              <p className="text-xs text-foreground/70 leading-relaxed line-clamp-3">
                                {summary.summaryContent}
                              </p>
                            </div>
                          );
                        })}
                      </CollapsibleContent>
                    </Collapsible>
                  </div>
                </div>
              )}
            </Card>
          </>
        )}

        {/* 3. Intermediate Groups - IMPROVED STYLING */}
        {hasIntermediateGroups && (
          <Card className="mb-8 bg-card border-border shadow-sm">
            <Collapsible
              open={intermediateGroupsExpanded}
              onOpenChange={setIntermediateGroupsExpanded}
            >
              <div className="p-6 pb-4">
                <CollapsibleTrigger asChild>
                  <button className="flex items-center justify-between w-full group">
                    <div className="flex items-center gap-2">
                      <Layers className="h-5 w-5 text-muted-foreground" />
                      <h3 className="text-lg font-medium text-foreground">
                        Zwischengruppen
                      </h3>
                      <span className="text-sm text-muted-foreground">
                        ({selectedRun!.intermediateGroups!.length} Gruppen)
                      </span>
                    </div>
                    <ChevronDown
                      className={cn(
                        "h-5 w-5 text-muted-foreground group-hover:text-foreground transition-all",
                        intermediateGroupsExpanded && "rotate-180"
                      )}
                    />
                  </button>
                </CollapsibleTrigger>
              </div>

              <CollapsibleContent>
                <div className="px-6 pb-6 space-y-4">
                  {selectedRun!.intermediateGroups!.map((group) => (
                    <Card key={group.id} className="p-4 bg-muted/30">
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-medium text-muted-foreground">
                              Gruppe {group.groupNumber}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {group.sourceCount} Quellen
                            </span>
                          </div>
                          <h4 className="font-medium">{group.heading}</h4>
                          {group.topic && (
                            <p className="text-sm text-muted-foreground mt-1">
                              {group.topic}
                            </p>
                          )}
                        </div>
                        <div className="flex gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
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
                            onClick={() =>
                              onOpenTextViewer({
                                title: `Gruppe ${group.groupNumber}: ${group.heading}`,
                                text: group.combinedContent,
                              })
                            }
                          >
                            <Maximize2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                      <p className="text-sm text-foreground/80 leading-relaxed line-clamp-3">
                        {group.combinedContent}
                      </p>
                      <div className="mt-3 pt-3 border-t border-border/50 flex items-center gap-3 text-xs text-muted-foreground">
                        <span>{group.modelUsed}</span>
                        <span>•</span>
                        <span>{group.tokensUsed.toLocaleString()} tokens</span>
                        <span>•</span>
                        <span>{formatCost(group.cost)}</span>
                      </div>
                    </Card>
                  ))}
                </div>
              </CollapsibleContent>
            </Collapsible>
          </Card>
        )}

        {/* 4. Kombinierter Text (Combined) */}
        {hasContent && (
          <Card className="mb-8 bg-card border-border shadow-sm">
            <div className="p-8">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-medium text-foreground">
                  Kombinierter Text
                </h2>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onOpenShorten}
                    disabled={!hasContent}
                  >
                    <Scissors className="h-4 w-4 mr-2" />
                    Kürzen
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onOpenCombinedRefinement}
                    disabled={!hasContent}
                  >
                    <MessageSquareText className="h-4 w-4 mr-2" />
                    Verfeinern
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      handleCopy(selectedRun!.combinedText, "kombiniert")
                    }
                  >
                    {copiedId === "kombiniert" ? (
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
        )}

        {/* Combine Button (if only quellen exist) */}
        {hasQuellenErgebnisse && !hasContent && (
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
              <Button onClick={onCombineTexts} disabled={isCombining}>
                {isCombining ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Layers className="h-4 w-4 mr-2" />
                )}
                Texte kombinieren
              </Button>
            </div>
          </Card>
        )}

        {/* No Run Yet */}
        {runs.length === 0 && (
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
        )}

        {/* 5. Ergebnisse pro Quelle */}
        {hasQuellenErgebnisse && (
          <div className="mt-8">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <BookOpen className="h-4 w-4" />
                Ergebnisse pro Quelle ({selectedRun!.quellenErgebnisse.length})
              </h3>
              {!hasContent && selectedRun!.quellenErgebnisse.some((qe) => qe.status === "success") && (
                <Button size="sm" variant="outline" onClick={onCombineTexts} disabled={isCombining}>
                  {isCombining ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <Layers className="h-4 w-4 mr-1" />
                  )}
                  Texte kombinieren
                </Button>
              )}
            </div>

            <div className="space-y-3">
              {selectedRun!.quellenErgebnisse.map((ergebnis) => (
                <Card key={ergebnis.id} className="p-4 bg-muted/10">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-foreground mb-1">
                        {ergebnis.quelleName}
                      </h4>
                      {ergebnis.status === "waiting" && (
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          <span className="text-sm">Text wird generiert...</span>
                        </div>
                      )}
                      {ergebnis.status === "no-content" && (
                        <div className="flex items-center gap-2 text-amber-600">
                          <AlertCircle className="h-4 w-4" />
                          <span className="text-sm">Kein verwertbarer Inhalt</span>
                        </div>
                      )}
                      {ergebnis.status === "success" && ergebnis.text && (
                        <p className="text-sm text-foreground/80 line-clamp-3">
                          {ergebnis.text}
                        </p>
                      )}
                    </div>
                    {ergebnis.status === "success" && ergebnis.text && (
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleCopy(ergebnis.text, ergebnis.id)}
                        >
                          {copiedId === ergebnis.id ? (
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
                              title: ergebnis.quelleName,
                              text: ergebnis.text,
                            })
                          }
                        >
                          <Maximize2 className="h-4 w-4" />
                        </Button>
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
