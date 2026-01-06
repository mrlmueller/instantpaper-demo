'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

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

function formatIsoDate(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString('de-DE');
  } catch {
    return iso;
  }
}

function formatIsoDateTime(iso: string | null): string {
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

function formatCompact(num: number): string {
  const n = Number(num || 0);
  if (!Number.isFinite(n)) return '0';
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M`;
  if (n >= 1_000) return `${Math.round(n / 100) / 10}k`;
  return String(Math.round(n));
}

function statusBadgeClass(status: string): string {
  if (status === 'success') return 'bg-primary text-primary-foreground border-transparent';
  return 'bg-destructive text-white border-transparent';
}

export function AdminUserStatsPanel({ uid, refreshNonce }: { uid: string; refreshNonce?: number }) {
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
  }, [uid, refreshNonce]);

  const summary = useMemo(() => data?.stats, [data]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-lg border bg-background p-4 space-y-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-6 w-28" />
            </div>
          ))}
        </div>
        <div className="rounded-lg border bg-background p-6 space-y-3">
          <Skeleton className="h-4 w-48" />
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || !summary) {
    return (
      <div className="rounded-lg border bg-background p-6">
        <p className="text-sm text-muted-foreground">Keine Statistiken verfügbar.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-lg border bg-background p-4">
          <p className="text-xs text-muted-foreground">Gesamtkosten</p>
          <p className="text-xl font-semibold text-foreground mt-1">{formatCost(summary.totalCost)}</p>
        </div>
        <div className="rounded-lg border bg-background p-4">
          <p className="text-xs text-muted-foreground">Verarbeitungen</p>
          <p className="text-xl font-semibold text-foreground mt-1">{formatNumber(summary.totalRuns)}</p>
        </div>
        <div className="rounded-lg border bg-background p-4">
          <p className="text-xs text-muted-foreground">Exporte</p>
          <p className="text-xl font-semibold text-foreground mt-1">{formatNumber(summary.exportCount)}</p>
        </div>
        <div className="rounded-lg border bg-background p-4">
          <p className="text-xs text-muted-foreground">Geschätzte Wörter</p>
          <p className="text-xl font-semibold text-foreground mt-1">{formatCompact(summary.totalWords)}</p>
        </div>
      </div>

      <div className="rounded-lg border bg-background p-6">
        <p className="text-sm font-medium text-foreground mb-4">Letzte Operationen</p>
        {data.operations.length === 0 ? (
          <p className="text-sm text-muted-foreground">Keine Operationen gefunden.</p>
        ) : (
          <div className="divide-y">
            {data.operations.map((op) => (
              <div key={op.operationId} className="py-3 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <Badge className={cn('rounded-md px-2 py-0.5 text-[11px] font-semibold', statusBadgeClass(op.status))}>
                    {op.status || 'unknown'}
                  </Badge>
                  <div className="min-w-0">
                    <p className="text-sm text-foreground truncate">{op.operationType || '-'}</p>
                    <p className="text-xs text-muted-foreground truncate">{op.model || '-'}</p>
                  </div>
                </div>

                <div className="flex items-center gap-4 text-xs text-muted-foreground shrink-0">
                  <span className="uppercase">{op.keySource || '-'}</span>
                  <span className="text-foreground">{formatCost(op.cost)}</span>
                  <span>{formatIsoDate(op.timestamp)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="p-6 gap-4">
          <div className="grid grid-cols-2 gap-4">
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
              <p className="text-xs text-muted-foreground">Export-Kosten</p>
              <p className="text-lg font-semibold text-foreground">{formatCost(summary.exportCost)}</p>
            </div>
          </div>

          <div className="text-xs text-muted-foreground">
            Member since: <span className="text-foreground">{formatIsoDateTime(summary.memberSince)}</span>
          </div>
        </Card>

        <Card className="p-6 gap-4">
          <p className="text-sm font-medium text-foreground">Modellnutzung</p>
          <div className="flex flex-wrap gap-2">
            {summary.modelUsage.length === 0 ? (
              <p className="text-sm text-muted-foreground">Keine Daten.</p>
            ) : (
              summary.modelUsage.map((m) => (
                <Badge key={m.model} variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-semibold">
                  {m.model}: {formatNumber(m.count)}
                </Badge>
              ))
            )}
          </div>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-lg border bg-background p-6">
          <p className="text-sm font-medium text-foreground mb-4">Aktivität (6 Monate)</p>
          {summary.runsByMonth.length === 0 ? (
            <p className="text-sm text-muted-foreground">Keine Daten.</p>
          ) : (
            <div className="space-y-2">
              {summary.runsByMonth.map((m) => (
                <div key={m.key || m.month} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">{m.month}</span>
                  <span className="text-foreground">{formatNumber(m.runs)} runs</span>
                  <span className="text-muted-foreground">{formatCost(m.cost)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border bg-background p-6">
          <p className="text-sm font-medium text-foreground mb-4">Kosten pro Projekt</p>
          {summary.costByProjekt.length === 0 ? (
            <p className="text-sm text-muted-foreground">Keine Daten.</p>
          ) : (
            <div className="space-y-2">
              {summary.costByProjekt.slice(0, 12).map((p) => (
                <div key={p.projektId} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-foreground truncate">{p.projektName}</span>
                  <span className="text-muted-foreground">{formatCost(p.cost)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

