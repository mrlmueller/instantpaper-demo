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
import { Sparkles, Clock } from 'lucide-react';

interface KapitelListProps {
  kapitels: Kapitel[];
  quellen: Quelle[];
}

export function KapitelList({ kapitels, quellen }: KapitelListProps) {
  const [selectedRuns, setSelectedRuns] = useState<Record<string, string | undefined>>({});

  useEffect(() => {
    const defaults: Record<string, string | undefined> = {};
    kapitels.forEach((kapitel) => {
      if (kapitel.runs && kapitel.runs.length > 0) {
        defaults[kapitel.id] = kapitel.runs[0].id;
      }
    });
    setSelectedRuns(defaults);
  }, [kapitels]);

  if (kapitels.length === 0) {
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
      {kapitels.map((kapitel) => {
        const assignedQuellen = quellen.filter((q) => kapitel.quelleIds?.includes(q.id));

        const currentRun: KapitelRun | undefined =
          kapitel.runs?.find((r) => r.id === selectedRuns[kapitel.id]) ||
          kapitel.runs?.[0];

        return (
          <div key={kapitel.id} className="border rounded-xl bg-white p-6 shadow-sm">
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
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Clock className="h-4 w-4" />
                      Run {currentRun.index} · {new Date(currentRun.createdAt).toLocaleString()} · Modell {currentRun.model}
                    </div>
                    <p className="mt-2 text-sm whitespace-pre-wrap">{currentRun.instruction}</p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {assignedQuellen.map((quelle) => {
                      const result = currentRun.results?.find((r) => r.quelleId === quelle.id);
                      return (
                        <div key={quelle.id} className="border rounded-lg p-4 bg-white">
                          <div className="flex items-center justify-between">
                            <h4 className="font-semibold text-sm">{quelle.title}</h4>
                            <Badge variant="outline">Quelle</Badge>
                          </div>
                          <div className="mt-2 rounded-md bg-muted p-3 max-h-64 overflow-y-auto">
                            <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">
                              {result?.resultContent || result?.result_content || 'Noch kein Ergebnis'}
                            </pre>
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
