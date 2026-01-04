'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

type RunsByMonthRow = { month: string; runs: number; cost: number; key?: string };
type CostByProjektRow = { projektId: string; projektName: string; cost: number };
type ModelUsageRow = { model: string; count: number };

type LiveUserStats = {
  totalCost: number;
  totalRuns: number;
  exportCost: number;
  exportCount: number;
  totalProjekte: number;
  totalKapitel: number;
  totalQuellen: number;
  totalWords: number;
  runsByMonth: RunsByMonthRow[];
  costByProjekt: CostByProjektRow[];
  modelUsage: ModelUsageRow[];
  memberSince: string;
};

type OperationRow = {
  operationId: string;
  timestamp: string | null;
  operationType: string;
  status: string;
  errorMessage: string | null;
  model: string | null;
  keySource: string | null;
  cost: number;
  outputTokens: number;
  projektId: string | null;
  projektName: string | null;
};

type StatsResponse = {
  stats: LiveUserStats;
  operations: OperationRow[];
  error?: string;
};

function formatIso(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('de-DE');
  } catch {
    return iso;
  }
}

function formatCost(cents: number): string {
  const num = Number(cents || 0);
  if (!Number.isFinite(num)) return '$0.00';
  return `$${(num / 100).toFixed(2)}`;
}

function formatNumber(num: number): string {
  const n = Number(num || 0);
  if (!Number.isFinite(n)) return '0';
  return n.toLocaleString('de-DE');
}

export function AdminUserStatsPanel({ uid }: { uid: string }) {
  const [data, setData] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/stats?operations_limit=25`, {
        cache: 'no-store',
      });
      const json = (await res.json()) as StatsResponse;
      if (!res.ok) throw new Error((json as any)?.error || 'Konnte Statistiken nicht laden.');
      setData(json);
    } catch (err: any) {
      toast.error('Statistiken', { description: err?.message || 'Konnte Statistiken nicht laden.' });
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  const summary = useMemo(() => data?.stats, [data]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Card className="p-6">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-6 w-24" />
              </div>
            ))}
          </div>
        </Card>
        <Card className="p-6">
          <Skeleton className="h-6 w-40 mb-4" />
          <Skeleton className="h-32 w-full" />
        </Card>
      </div>
    );
  }

  if (!data || !summary) {
    return (
      <Card className="p-6">
        <p className="text-sm text-muted-foreground">Keine Statistiken verfügbar.</p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-muted-foreground">Gesamtkosten</p>
            <p className="text-lg font-semibold text-foreground">{formatCost(summary.totalCost)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Runs</p>
            <p className="text-lg font-semibold text-foreground">{formatNumber(summary.totalRuns)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Exporte</p>
            <p className="text-lg font-semibold text-foreground">{formatNumber(summary.exportCount)}</p>
            <p className="text-xs text-muted-foreground">{formatCost(summary.exportCost)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Member since</p>
            <p className="text-sm font-medium text-foreground">{formatIso(summary.memberSince)}</p>
          </div>

          <div>
            <p className="text-xs text-muted-foreground">Projekte</p>
            <p className="text-lg font-semibold text-foreground">{formatNumber(summary.totalProjekte)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Kapitel</p>
            <p className="text-lg font-semibold text-foreground">{formatNumber(summary.totalKapitel)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Quellen</p>
            <p className="text-lg font-semibold text-foreground">{formatNumber(summary.totalQuellen)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Wörter (~)</p>
            <p className="text-lg font-semibold text-foreground">{formatNumber(summary.totalWords)}</p>
          </div>
        </div>
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        <Card className="p-6">
          <h3 className="text-sm font-medium text-foreground mb-4">Aktivität (6 Monate)</h3>
          <div className="space-y-2">
            {summary.runsByMonth.map((m) => (
              <div key={m.key || m.month} className="flex items-center justify-between gap-3">
                <span className="text-sm text-muted-foreground">{m.month}</span>
                <span className="text-sm text-foreground">{m.runs} runs</span>
                <span className="text-sm text-muted-foreground">{formatCost(m.cost)}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-6">
          <h3 className="text-sm font-medium text-foreground mb-4">Kosten pro Projekt</h3>
          <div className="space-y-2">
            {summary.costByProjekt.slice(0, 12).map((p) => (
              <div key={p.projektId} className="flex items-center justify-between gap-3">
                <span className="text-sm text-foreground truncate">{p.projektName}</span>
                <span className="text-sm text-muted-foreground">{formatCost(p.cost)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card className="p-6">
        <h3 className="text-sm font-medium text-foreground mb-4">Modellnutzung</h3>
        <div className="flex flex-wrap gap-2">
          {summary.modelUsage.map((m) => (
            <Badge key={m.model} variant="secondary">
              {m.model}: {formatNumber(m.count)}
            </Badge>
          ))}
        </div>
      </Card>

      <Card className="p-6">
        <h3 className="text-sm font-medium text-foreground mb-4">Letzte Operationen</h3>
        {data.operations.length === 0 ? (
          <p className="text-sm text-muted-foreground">Keine Operationen gefunden.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Zeit</TableHead>
                  <TableHead>Typ</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Key</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Kosten</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.operations.map((op) => (
                  <TableRow key={op.operationId}>
                    <TableCell className="text-xs text-muted-foreground">{formatIso(op.timestamp)}</TableCell>
                    <TableCell className="text-sm">{op.operationType || '-'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{op.model || '-'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{op.keySource || '-'}</TableCell>
                    <TableCell className="text-xs">
                      {op.status ? (
                        <Badge
                          variant={op.status === 'success' ? 'default' : 'outline'}
                          className={
                            op.status === 'success'
                              ? 'bg-emerald-600 text-white border-transparent'
                              : 'border-destructive text-destructive'
                          }
                        >
                          {op.status}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right text-sm">{formatCost(op.cost)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}
