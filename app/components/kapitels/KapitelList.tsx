'use client';

import { useState, useEffect } from 'react';
import type { Kapitel, KapitelRun } from '@/app/actions/kapitels';
import type { Quelle } from '@/app/actions/quellen';
import { ProcessKapitelDialog } from './ProcessKapitelDialog';
import { ManageKapitelQuellenDialog } from './ManageKapitelQuellenDialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Sparkles, Clock, Loader2 } from 'lucide-react';
import { collection, limit, onSnapshot, orderBy, query } from 'firebase/firestore';
import { firestoreClient } from '@/app/lib/firebase/firestoreClient';
import { useAuth } from '@/app/components/providers/AuthProvider';

interface KapitelListProps {
  kapitels: Kapitel[];
  quellen: Quelle[];
}

export function KapitelList({ kapitels, quellen }: KapitelListProps) {
  const { user } = useAuth();
  const [selectedRuns, setSelectedRuns] = useState<Record<string, string | undefined>>({});
  const [kapitelState, setKapitelState] = useState<Kapitel[]>(kapitels);

  useEffect(() => {
    setKapitelState(kapitels);
    const defaults: Record<string, string | undefined> = {};
    kapitels.forEach((kapitel) => {
      if (kapitel.runs && kapitel.runs.length > 0) {
        defaults[kapitel.id] = kapitel.runs[0].id;
      }
    });
    setSelectedRuns(defaults);
  }, [kapitels]);

  // ensure a selected run exists when runs change
  useEffect(() => {
    const nextSelected = { ...selectedRuns };
    let changed = false;
    kapitelState.forEach((kapitel) => {
      if (kapitel.runs && kapitel.runs.length > 0) {
        const current = nextSelected[kapitel.id];
        if (!current || !kapitel.runs.some((r) => r.id === current)) {
          nextSelected[kapitel.id] = kapitel.runs[0].id;
          changed = true;
        }
      }
    });
    if (changed) {
      setSelectedRuns(nextSelected);
    }
  }, [kapitelState]);

  // Live subscribe to runs and results for each Kapitel
  useEffect(() => {
    if (!user?.uid || kapitelState.length === 0) return;
    const unsubscribes: Array<() => void> = [];

    kapitelState.forEach((kapitel) => {
      const runsRef = collection(
        firestoreClient,
        'users',
        user.uid,
        'kapitels',
        kapitel.id,
        'runs'
      );
      const runsUnsub = onSnapshot(
        query(runsRef, orderBy('index', 'desc'), limit(5)),
        (snapshot) => {
          const runs: KapitelRun[] = snapshot.docs.map((runDoc) => {
            const data: any = runDoc.data();
            return {
              id: runDoc.id,
              index: data.index || 0,
              instruction: data.instruction || '',
              model: data.model || '',
              createdAt:
                data.createdAt?.toDate?.()?.toISOString() ||
                data.created_at?.toDate?.()?.toISOString() ||
                new Date().toISOString(),
              results: [],
            };
          });

          // update run list immediately
          setKapitelState((prev) =>
            prev.map((k) => (k.id === kapitel.id ? { ...k, runs } : k))
          );

          // subscribe to results for each run
          runs.forEach((run) => {
            const resultsRef = collection(
              firestoreClient,
              'users',
              user.uid,
              'kapitels',
              kapitel.id,
              'runs',
              run.id,
              'results'
            );
            const resUnsub = onSnapshot(resultsRef, (resSnap) => {
              const results = resSnap.docs.map((resDoc) => {
                const resData: any = resDoc.data();
                return {
                  quelleId: resDoc.id,
                  resultContent:
                    resData.result_content ??
                    resData.resultContent ??
                    resData.content ??
                    '',
                  hasContent: resData.has_content ?? resData.hasContent ?? true,
                  modelUsed: resData.model_used ?? resData.modelUsed ?? '',
                  tokensUsed: resData.tokens_used ?? resData.tokensUsed ?? 0,
                  inputTokens: resData.input_tokens ?? resData.inputTokens ?? 0,
                  cachedInputTokens: resData.cached_input_tokens ?? resData.cachedInputTokens ?? 0,
                  outputTokens: resData.output_tokens ?? resData.outputTokens ?? 0,
                  reasoningTokens: resData.reasoning_tokens ?? resData.reasoningTokens ?? 0,
                  cost: resData.cost ?? 0,
                  createdAt:
                    resData.created_at?.toDate?.()?.toISOString() ||
                    resData.createdAt?.toDate?.()?.toISOString() ||
                    new Date().toISOString(),
                };
              });

              setKapitelState((prev) =>
                prev.map((k) => {
                  if (k.id !== kapitel.id) return k;
                  const updatedRuns =
                    k.runs?.map((r) => (r.id === run.id ? { ...r, results } : r)) || [];
                  return { ...k, runs: updatedRuns };
                })
              );
            });
            unsubscribes.push(resUnsub);
          });
        }
      );
      unsubscribes.push(runsUnsub);
    });

    return () => {
      unsubscribes.forEach((u) => u());
    };
  }, [user?.uid, kapitelState.map((k) => k.id).join('|')]);

  if (kapitelState.length === 0) {
    return (
      <div className="text-center py-12 rounded-lg border bg-white">
        <Sparkles className="mx-auto h-10 w-10 text-gray-400" />
        <h3 className="mt-2 text-lg font-semibold text-gray-900">Noch keine Kapiteln</h3>
        <p className="mt-1 text-sm text-gray-500">Lege ein Kapitel an und ordne Quellen zu.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {kapitelState.map((kapitel) => {
        const assignedQuellen = quellen.filter((q) => kapitel.quelleIds?.includes(q.id));

        const currentRun: KapitelRun | undefined =
          kapitel.runs?.find((r) => r.id === selectedRuns[kapitel.id]) ||
          kapitel.runs?.[0];

        return (
          <div
            key={kapitel.id}
            className="border rounded-xl bg-gradient-to-b from-white via-white to-gray-50 p-6 shadow-sm ring-1 ring-gray-100"
          >
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-2xl font-semibold">{kapitel.title}</h2>
                  <Badge variant="outline">{assignedQuellen.length} Quellen</Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  Erstellt am {new Date(kapitel.createdAt).toLocaleString()}
                </p>
              </div>
              <div className="flex gap-2 flex-wrap">
                <ProcessKapitelDialog kapitel={kapitel} quellen={assignedQuellen} />
                <ManageKapitelQuellenDialog kapitel={kapitel} quellen={quellen} />
              </div>
            </div>

            <div className="mt-4 space-y-2">
              <p className="text-sm font-medium text-muted-foreground">Zugeordnete Quellen</p>
              {assignedQuellen.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Noch keine Quellen zugeordnet.
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {assignedQuellen.map((q) => (
                    <Badge key={q.id} variant="secondary">
                      {q.title}
                    </Badge>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-6 border-t pt-4 space-y-3">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">Läufe</span>
                </div>
                {kapitel.runs && kapitel.runs.length > 0 ? (
                  <Select
                    value={selectedRuns[kapitel.id] || kapitel.runs[0].id}
                    onValueChange={(value) =>
                      setSelectedRuns((prev) => ({ ...prev, [kapitel.id]: value }))
                    }
                  >
                    <SelectTrigger className="w-44">
                      <SelectValue placeholder="Run auswählen" />
                    </SelectTrigger>
                    <SelectContent>
                      {kapitel.runs.map((run) => (
                        <SelectItem key={run.id} value={run.id}>
                          Run {run.index} · {new Date(run.createdAt).toLocaleString()}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    Noch keine Läufe – verarbeite das Kapitel.
                  </div>
                )}
              </div>

              {currentRun ? (
                <div className="space-y-4">
                  <div className="rounded-lg border p-4 bg-muted/50">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Clock className="h-4 w-4" />
                        Run {currentRun.index} · {new Date(currentRun.createdAt).toLocaleString()} · Modell {currentRun.model}
                      </div>
                      {currentRun.results && currentRun.results.length > 0 && (
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary" className="font-mono">
                            Total: ${(currentRun.results.reduce((sum, r) => sum + (r.cost || 0), 0)).toFixed(4)}
                          </Badge>
                          <Badge variant="outline" className="text-xs">
                            {currentRun.results.reduce((sum, r) => sum + (r.tokensUsed || 0), 0).toLocaleString()} tokens
                          </Badge>
                        </div>
                      )}
                    </div>
                    <p className="mt-2 text-sm whitespace-pre-wrap">{currentRun.instruction}</p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {assignedQuellen.map((quelle) => {
                      const result = currentRun.results?.find((r) => r.quelleId === quelle.id);
                      const isNoContent = result?.hasContent === false;
                      return (
                        <div key={quelle.id} className="border rounded-lg p-4 bg-white">
                          <div className="flex items-center justify-between flex-wrap gap-2">
                            <h4 className="font-semibold text-sm">{quelle.title}</h4>
                            <div className="flex items-center gap-1">
                              {isNoContent && (
                                <Badge
                                  variant="outline"
                                  className="text-[11px] text-amber-700 border-amber-200 bg-amber-50"
                                >
                                  Keine verwertbaren Infos
                                </Badge>
                              )}
                              {result?.cost !== undefined && result.cost > 0 && (
                                <Badge variant="secondary" className="font-mono text-xs">
                                  ${result.cost.toFixed(4)}
                                </Badge>
                              )}
                              <Badge variant="outline">Quelle</Badge>
                            </div>
                          </div>
                          {result?.tokensUsed !== undefined && result.tokensUsed > 0 && (
                            <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                              <span>In: {result.inputTokens?.toLocaleString() ?? 0}</span>
                              {result.cachedInputTokens > 0 && (
                                <span className="text-green-600 font-medium">(cached: {result.cachedInputTokens.toLocaleString()})</span>
                              )}
                              <span>·</span>
                              <span>Out: {result.outputTokens?.toLocaleString() ?? 0}</span>
                              {result.reasoningTokens > 0 && (
                                <>
                                  <span>·</span>
                                  <span className="text-amber-600 font-medium">Reasoning: {result.reasoningTokens.toLocaleString()}</span>
                                </>
                              )}
                              <span>·</span>
                              <span>Total: {result.tokensUsed.toLocaleString()}</span>
                            </div>
                          )}
                          <div className="mt-2 rounded-md bg-muted p-3 max-h-64 overflow-y-auto">
                            {result?.resultContent || result?.result_content ? (
                              <pre
                                className={`whitespace-pre-wrap text-sm leading-relaxed font-sans ${
                                  isNoContent ? 'text-muted-foreground italic' : ''
                                }`}
                              >
                                {result?.resultContent || result?.result_content}
                              </pre>
                            ) : (
                              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Ergebnis wird verarbeitet...
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  Keine Ergebnisse vorhanden. Starte einen Run für dieses Kapitel.
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
