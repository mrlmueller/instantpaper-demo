'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';

type MonthRow = { key: string; costUsd: number; count: number };
type BucketRow = MonthRow;

type TopUserRow = {
  uid: string;
  email?: string | null;
  displayName?: string | null;
  costUsd: number;
  count: number;
};

type BreakdownRow = { count: number; costUsd: number; credits: number } & Record<string, unknown>;

type MissingIndexState = { url: string | null; message: string };

type CostsSummaryResponse = {
  range: {
    preset: 'all' | 'custom';
    bucket: 'month' | 'day';
    startKey: string;
    endKey: string;
    start: string;
    endExclusive: string;
    keys: string[];
    note?: string;
  };
  totals: {
    costUsd: number;
    count: number;
    avgCostUsd: number;
    creditsEstimated: number;
    creditsTotal: number | null;
    defaultSpendRate: number;
    usersWithCosts: number;
  };
  byMonth: BucketRow[];
  byDay: BucketRow[];
  topUsers: TopUserRow[];
  scan: {
    enabled: boolean;
    scanLimit: number;
    operationsScanned: number;
    complete: boolean;
    totals: { costUsd: number; credits: number; count: number };
    byOperationType: BreakdownRow[];
    byModel: BreakdownRow[];
    byStatus: BreakdownRow[];
    byKeySource: BreakdownRow[];
  };
  error?: string;
  createIndexUrl?: string | null;
};

type OperationRow = {
  id: string;
  docPath: string;
  userId: string | null;
  operationId: string;
  timestamp: string | null;
  status: string;
  errorMessage: string | null;
  operationType: string;
  model: string | null;
  keySource: string | null;
  costUsd: number;
  creditsDebited: number;
  spendRate: number | null;
  tokens?: {
    inputTokens: number;
    cachedInputTokens: number;
    outputTokens: number;
    totalTokens: number;
  };
};

type CostsOperationsResponse = {
  operations?: OperationRow[];
  nextCursor?: string | null;
  error?: string;
  createIndexUrl?: string | null;
};

function addDays(base: Date, delta: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + delta);
  return d;
}

function addMonthsLocal(base: Date, delta: number): Date {
  const d = new Date(base.getFullYear(), base.getMonth(), 1);
  d.setMonth(d.getMonth() + delta);
  return d;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function toDateKeyLocal(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function toMonthKeyLocal(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function isMonthKey(value: string): boolean {
  return /^[0-9]{4}-[0-9]{2}$/.test(String(value || '').trim());
}

function isDateKey(value: string): boolean {
  return /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(String(value || '').trim());
}

function formatUsd(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n) || n <= 0) return '$0.00';
  return `$${n.toFixed(2)}`;
}

function formatCredits(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '0';
  const abs = Math.abs(n);
  const maximumFractionDigits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return n.toLocaleString('de-DE', { maximumFractionDigits });
}

function formatNumber(num: number | null | undefined): string {
  const n = Number(num ?? 0);
  if (!Number.isFinite(n)) return '0';
  return Math.max(0, Math.round(n)).toLocaleString('de-DE');
}

function formatIso(value: string | null | undefined): string {
  if (!value) return '-';
  try {
    return new Date(value).toLocaleString('de-DE', {
      year: '2-digit',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return value;
  }
}

function extractFirstUrl(value: string | null | undefined): string | null {
  const raw = String(value || '');
  const match = raw.match(/https?:\/\/\S+/);
  if (!match) return null;
  return match[0].replace(/[).,;\\]}>]+$/, '');
}

function isLikelyMissingFirestoreIndexMessage(value: string | null | undefined): boolean {
  const raw = String(value || '')
    .trim()
    .toLowerCase();
  if (!raw) return false;
  return (
    raw.includes('firestore index missing') ||
    raw.includes('firestore/indexes?create_exemption=') ||
    raw.includes('firestore/indexes?create_composite=') ||
    (raw.includes('collection_group') && raw.includes('timestamp') && raw.includes('index'))
  );
}

function rowLabel(row: TopUserRow): string {
  const display = String(row.displayName || '').trim();
  const email = String(row.email || '').trim();
  if (display && email) return `${display} (${email})`;
  return display || email || row.uid;
}

function statusBadgeClass(status: string): string {
  const s = String(status || '').trim().toLowerCase();
  if (s === 'success') return 'bg-primary text-primary-foreground border-transparent';
  if (s === 'running' || s === 'reserved') return 'bg-amber-500 text-white border-transparent';
  if (s === 'skipped') return 'bg-muted text-foreground border-transparent';
  if (s === 'blocked') return 'bg-destructive text-white border-transparent';
  if (s === 'error') return 'bg-destructive text-white border-transparent';
  return 'bg-muted text-foreground border-transparent';
}

function defaultRange(): { startKey: string; endKey: string } {
  const now = new Date();
  const endKey = toDateKeyLocal(now);
  const startKey = endKey;
  return { startKey, endKey };
}

function BucketBar({ row, maxCost }: { row: BucketRow; maxCost: number }) {
  const pct = maxCost > 0 ? Math.round((row.costUsd / maxCost) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-20 shrink-0 text-xs text-muted-foreground">{row.key}</div>
      <div className="min-w-0 flex-1">
        <div className="h-2 w-full rounded-full bg-muted/60 overflow-hidden">
          <div className="h-2 rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
        </div>
      </div>
      <div className="w-36 shrink-0 text-right text-xs text-foreground">
        {formatUsd(row.costUsd)} · {formatNumber(row.count)} ops
      </div>
    </div>
  );
}

function BreakdownBadges({
  title,
  rows,
  labelKey,
}: {
  title: string;
  rows: BreakdownRow[];
  labelKey: string;
}) {
  return (
    <Card className="p-6 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">Top {Math.min(25, rows.length)}</p>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Keine Daten.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {rows.slice(0, 25).map((r) => {
            const label = String((r as any)[labelKey] ?? labelKey);
            return (
              <Badge key={`${label}-${String(r.count)}`} variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-semibold">
                {label}: {formatUsd(Number(r.costUsd || 0))} · {formatNumber(Number(r.count || 0))}
              </Badge>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function OperationsTable({
  preset,
  startKey,
  endKey,
  onMissingIndex,
}: {
  preset: 'all' | 'custom';
  startKey: string;
  endKey: string;
  onMissingIndex?: (state: MissingIndexState | null) => void;
}) {
  const [rows, setRows] = useState<OperationRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [indexLink, setIndexLink] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = async (cursor: string | null) => {
    const qs = new URLSearchParams();
    if (preset === 'all') {
      qs.set('preset', 'all');
    } else {
      qs.set('start', startKey);
      qs.set('end', endKey);
    }
    qs.set('limit', '50');
    if (cursor) qs.set('cursor', cursor);
    const url = `/api/admin/costs/operations?${qs.toString()}`;

    const res = await fetch(url, { method: 'GET', cache: 'no-store' });
    const data = (await res.json().catch(() => ({}))) as CostsOperationsResponse;
    if (!res.ok) {
      const message = String(data?.error || 'Operationen konnten nicht geladen werden.');
      const err = new Error(message) as Error & { createIndexUrl?: string | null };
      err.createIndexUrl = typeof data?.createIndexUrl === 'string' ? data.createIndexUrl : null;
      throw err;
    }

    const ops = Array.isArray(data.operations) ? data.operations : [];
    const next = typeof data.nextCursor === 'string' ? data.nextCursor : null;
    return { operations: ops, nextCursor: next };
  };

  const reload = async () => {
    setLoading(true);
    try {
      const { operations, nextCursor } = await load(null);
      setRows(operations);
      setNextCursor(nextCursor);
      setIndexLink(null);
      setLoadError(null);
      onMissingIndex?.(null);
    } catch (err: any) {
      console.error('Costs operations reload failed:', err);
      const message = String(err?.message || 'Operationen konnten nicht geladen werden.');
      const url = (typeof err?.createIndexUrl === 'string' ? err.createIndexUrl : null) || extractFirstUrl(message);
      setIndexLink(url || null);
      setLoadError(message);
      if (url || isLikelyMissingFirestoreIndexMessage(message)) {
        onMissingIndex?.({ url: url || null, message });
      } else {
        onMissingIndex?.(null);
      }
      toast.error('Costs', { description: message });
      setRows([]);
      setNextCursor(null);
    } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    if (moreLoading || !nextCursor) return;
    setMoreLoading(true);
    try {
      const { operations, nextCursor: next } = await load(nextCursor);
      setRows((prev) => [...prev, ...operations]);
      setNextCursor(next);
    } catch (err: any) {
      console.error('Costs operations load more failed:', err);
      const message = String(err?.message || 'Operationen konnten nicht geladen werden.');
      const url = (typeof err?.createIndexUrl === 'string' ? err.createIndexUrl : null) || extractFirstUrl(message);
      setIndexLink(url || null);
      setLoadError(message);
      if (url || isLikelyMissingFirestoreIndexMessage(message)) {
        onMissingIndex?.({ url: url || null, message });
      } else {
        onMissingIndex?.(null);
      }
      toast.error('Costs', { description: message });
    } finally {
      setMoreLoading(false);
    }
  };

  useEffect(() => {
    setRows([]);
    setNextCursor(null);
    setQuery('');
    setIndexLink(null);
    setLoadError(null);
    onMissingIndex?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, startKey, endKey]);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, startKey, endKey]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      return (
        String(r.userId || '')
          .toLowerCase()
          .includes(q) ||
        String(r.operationType || '')
          .toLowerCase()
          .includes(q) ||
        String(r.model || '')
          .toLowerCase()
          .includes(q) ||
        String(r.status || '')
          .toLowerCase()
          .includes(q)
      );
    });
  }, [rows, query]);

  return (
    <Card className="p-6 space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-foreground">Operationen</p>
          <p className="text-xs text-muted-foreground">Neueste Operationen im Zeitraum (Load more für weitere).</p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Suche (uid, model, status, type)…"
            className="h-9 w-full sm:w-72"
          />
          <Button variant="outline" size="sm" className="h-9" onClick={reload} disabled={loading}>
            Refresh
          </Button>
        </div>
      </div>

      {indexLink ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 space-y-2">
          <p className="text-sm font-semibold text-foreground">Firestore Index fehlt</p>
          <p className="text-xs text-muted-foreground">Erstelle den Index über diesen Link:</p>
          <p className="text-xs text-muted-foreground">
            Alternativ (Repo hat `firestore.indexes.json`): <code className="text-xs">firebase deploy --only firestore:indexes</code>
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <code className="text-xs break-all">{indexLink}</code>
            <div className="flex items-center gap-2">
              <Button asChild variant="outline" size="sm" className="h-8">
                <a href={indexLink} target="_blank" rel="noreferrer">
                  Open
                </a>
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8"
                onClick={() => navigator.clipboard?.writeText(indexLink)}
              >
                Copy
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="space-y-2">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">{loadError ? 'Operationen konnten nicht geladen werden.' : 'Keine Operationen gefunden.'}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Cost</TableHead>
              <TableHead className="text-right">Credits</TableHead>
              <TableHead className="text-right">Tokens</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((r) => (
              <TableRow key={r.docPath}>
                <TableCell className="text-xs text-muted-foreground">{formatIso(r.timestamp)}</TableCell>
                <TableCell className="text-xs">
                  {r.userId ? (
                    <Link href={`/admin/users/${encodeURIComponent(r.userId)}`} className="hover:underline">
                      {r.userId}
                    </Link>
                  ) : (
                    '-'
                  )}
                </TableCell>
                <TableCell>
                  <Badge className={cn('rounded-md px-2 py-0.5 text-[11px] font-semibold', statusBadgeClass(r.status))}>
                    {r.status || 'unknown'}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-foreground">{r.operationType || '-'}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{r.model || '-'}</TableCell>
                <TableCell className="text-xs text-right text-foreground">{formatUsd(r.costUsd)}</TableCell>
                <TableCell className="text-xs text-right text-muted-foreground">{formatCredits(r.creditsDebited)}</TableCell>
                <TableCell className="text-xs text-right text-muted-foreground">{formatNumber(r.tokens?.totalTokens ?? 0)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Loaded: <span className="text-foreground">{formatNumber(rows.length)}</span>
          {query.trim() ? (
            <>
              {' '}
              · Visible: <span className="text-foreground">{formatNumber(filtered.length)}</span>
            </>
          ) : null}
        </p>
        <Button variant="outline" size="sm" className="h-9" onClick={loadMore} disabled={!nextCursor || moreLoading || loading}>
          {moreLoading ? 'Loading…' : nextCursor ? 'Load more' : 'No more'}
        </Button>
      </div>
    </Card>
  );
}

export function AdminCostsDashboard() {
  const defaults = useMemo(() => defaultRange(), []);
  const [preset, setPreset] = useState<'day' | 'week' | 'month' | 'all' | 'custom'>('day');
  const [rangeKind, setRangeKind] = useState<'month' | 'date'>('date');
  const [startKey, setStartKey] = useState(defaults.startKey);
  const [endKey, setEndKey] = useState(defaults.endKey);
  const [scanEnabled, setScanEnabled] = useState(false);
  const [scanLimit, setScanLimit] = useState(5000);
  const [data, setData] = useState<CostsSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [summaryMissingIndex, setSummaryMissingIndex] = useState<MissingIndexState | null>(null);
  const [opsMissingIndex, setOpsMissingIndex] = useState<MissingIndexState | null>(null);

  const bucketRows = useMemo(() => {
    if (!data) return [] as BucketRow[];
    return data.range.bucket === 'day' ? data.byDay || [] : data.byMonth || [];
  }, [data]);

  const maxBucketCost = useMemo(() => {
    return bucketRows.reduce((max, r) => Math.max(max, Number(r.costUsd || 0)), 0);
  }, [bucketRows]);

  const applyPreset = (next: typeof preset) => {
    const now = new Date();
    setPreset(next);

    if (next === 'day') {
      setRangeKind('date');
      const today = toDateKeyLocal(now);
      setStartKey(today);
      setEndKey(today);
      return;
    }

    if (next === 'week') {
      setRangeKind('date');
      const end = toDateKeyLocal(now);
      const start = toDateKeyLocal(addDays(now, -6));
      setStartKey(start);
      setEndKey(end);
      return;
    }

    if (next === 'month') {
      setRangeKind('date');
      const end = toDateKeyLocal(now);
      const start = toDateKeyLocal(addDays(now, -29));
      setStartKey(start);
      setEndKey(end);
      return;
    }

    if (next === 'all') {
      setRangeKind('month');
      // start/end are ignored for preset=all; keep current keys so the UI can return to custom easily.
      return;
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (preset === 'all') {
        qs.set('preset', 'all');
      } else {
        qs.set('start', startKey);
        qs.set('end', endKey);
      }
      if (scanEnabled) qs.set('scan_limit', String(Math.max(0, Math.min(20000, Number(scanLimit) || 0))));
      const res = await fetch(`/api/admin/costs/summary?${qs.toString()}`, { cache: 'no-store' });
      const json = (await res.json().catch(() => ({}))) as CostsSummaryResponse;
      if (!res.ok) {
        const message = String(json?.error || 'Costs summary konnte nicht geladen werden.');
        const err = new Error(message) as Error & { createIndexUrl?: string | null };
        err.createIndexUrl = typeof json?.createIndexUrl === 'string' ? json.createIndexUrl : null;
        throw err;
      }
      setData(json);
      setSummaryMissingIndex(null);
    } catch (err: any) {
      console.error('Costs summary load failed:', err);
      const message = String(err?.message || 'Costs summary konnte nicht geladen werden.');
      const url = (typeof err?.createIndexUrl === 'string' ? err.createIndexUrl : null) || extractFirstUrl(message);
      if (url || isLikelyMissingFirestoreIndexMessage(message)) {
        setSummaryMissingIndex({ url: url || null, message });
      } else {
        setSummaryMissingIndex(null);
      }
      toast.error('Costs', { description: message });
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, startKey, endKey, scanEnabled]);

  const scanNote = useMemo(() => {
    if (!data?.scan?.enabled) return null;
    const scanned = Number(data.scan.operationsScanned || 0);
    const limit = Number(data.scan.scanLimit || 0);
    const complete = data.scan.complete === true;
    if (complete) return `Breakdown basiert auf allen Operationen im Zeitraum (${formatNumber(scanned)} ops).`;
    return `Breakdown basiert auf den letzten ${formatNumber(scanned)} / ${formatNumber(limit)} Operationen (Sample).`;
  }, [data]);

  const missingIndex = opsMissingIndex || summaryMissingIndex;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Costs</h2>
          <p className="text-sm text-muted-foreground">Globaler Überblick über OpenAI-Kosten und Credits.</p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant={preset === 'day' ? 'default' : 'outline'}
                className="h-8"
                onClick={() => applyPreset('day')}
              >
                Day
              </Button>
              <Button
                type="button"
                size="sm"
                variant={preset === 'week' ? 'default' : 'outline'}
                className="h-8"
                onClick={() => applyPreset('week')}
              >
                Week
              </Button>
              <Button
                type="button"
                size="sm"
                variant={preset === 'month' ? 'default' : 'outline'}
                className="h-8"
                onClick={() => applyPreset('month')}
              >
                Month
              </Button>
              <Button
                type="button"
                size="sm"
                variant={preset === 'all' ? 'default' : 'outline'}
                className="h-8"
                onClick={() => applyPreset('all')}
              >
                All
              </Button>

              {preset !== 'all' && preset !== 'custom' ? (
                <Badge variant="secondary" className="h-8 rounded-md px-2 py-0.5 text-xs font-semibold">
                  {rangeKind === 'date' ? 'YYYY-MM-DD' : 'YYYY-MM'}
                </Badge>
              ) : null}
            </div>

            {preset === 'all' ? (
              <p className="text-xs text-muted-foreground">All-time totals (Trend: last 12 months).</p>
            ) : (
              <div className="flex items-center gap-2">
                <div className="space-y-1">
                  <p className="text-[11px] text-muted-foreground">Start</p>
                  <Input
                    type={rangeKind === 'date' ? 'date' : 'month'}
                    className="h-9 w-[160px]"
                    value={startKey}
                    onChange={(e) => {
                      setPreset('custom');
                      setStartKey(e.target.value);
                      if (isDateKey(e.target.value)) setRangeKind('date');
                      if (isMonthKey(e.target.value)) setRangeKind('month');
                    }}
                  />
                </div>
                <div className="space-y-1">
                  <p className="text-[11px] text-muted-foreground">End</p>
                  <Input
                    type={rangeKind === 'date' ? 'date' : 'month'}
                    className="h-9 w-[160px]"
                    value={endKey}
                    onChange={(e) => {
                      setPreset('custom');
                      setEndKey(e.target.value);
                      if (isDateKey(e.target.value)) setRangeKind('date');
                      if (isMonthKey(e.target.value)) setRangeKind('month');
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <Switch checked={scanEnabled} onCheckedChange={setScanEnabled} />
                <span className="text-sm text-foreground">Detail Scan</span>
              </div>
              {scanEnabled ? (
                <div className="flex items-center gap-2">
                  <Input
                    value={String(scanLimit)}
                    onChange={(e) => setScanLimit(Number(e.target.value || 0))}
                    className="h-8 w-24 text-xs"
                    inputMode="numeric"
                  />
                  <span className="text-xs text-muted-foreground">max ops</span>
                </div>
              ) : null}
            </div>
            <Button variant="outline" size="sm" className="h-9" onClick={load} disabled={loading}>
              Refresh
            </Button>
          </div>
        </div>
      </div>

      {missingIndex ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 space-y-2">
          <p className="text-sm font-semibold text-foreground">Firestore Index fehlt</p>
          <p className="text-xs text-muted-foreground">
            Für diese Ansicht wird ein Firestore Index benötigt. Sobald er erstellt/deployed ist, laden die Tabellen automatisch.
          </p>
          <p className="text-xs text-muted-foreground">
            CLI: <code className="text-xs">firebase deploy --only firestore:indexes</code>
          </p>
          {missingIndex.url ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <code className="text-xs break-all">{missingIndex.url}</code>
              <div className="flex items-center gap-2">
                <Button asChild variant="outline" size="sm" className="h-8">
                  <a href={missingIndex.url} target="_blank" rel="noreferrer">
                    Open
                  </a>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8"
                  onClick={() => navigator.clipboard?.writeText(missingIndex.url || '')}
                >
                  Copy
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{missingIndex.message}</p>
          )}
        </div>
      ) : null}

      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="rounded-lg border bg-background p-4 space-y-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-6 w-28" />
              </div>
            ))}
          </div>
          <Card className="p-6 space-y-3">
            <Skeleton className="h-4 w-48" />
            {[...Array(6)].map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </Card>
        </div>
      ) : !data ? (
        <Card className="p-6">
          <p className="text-sm text-muted-foreground">Keine Daten verfügbar.</p>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="rounded-lg border bg-background p-4">
              <p className="text-xs text-muted-foreground">Total Cost (USD)</p>
              <p className="text-xl font-semibold text-foreground mt-1">{formatUsd(data.totals.costUsd)}</p>
            </div>
            <div className="rounded-lg border bg-background p-4">
              <p className="text-xs text-muted-foreground">Operations</p>
              <p className="text-xl font-semibold text-foreground mt-1">{formatNumber(data.totals.count)}</p>
            </div>
            <div className="rounded-lg border bg-background p-4">
              <p className="text-xs text-muted-foreground">Avg Cost / Op</p>
              <p className="text-xl font-semibold text-foreground mt-1">{formatUsd(data.totals.avgCostUsd)}</p>
            </div>
            <div className="rounded-lg border bg-background p-4">
              <p className="text-xs text-muted-foreground">{data.totals.creditsTotal != null ? 'Credits (actual)' : 'Credits (est.)'}</p>
              <p className="text-xl font-semibold text-foreground mt-1">
                {formatCredits(data.totals.creditsTotal ?? data.totals.creditsEstimated)}
              </p>
              <p className="text-[11px] text-muted-foreground mt-1">
                Spend Rate: {formatCredits(data.totals.defaultSpendRate)} / $1
                {data.totals.creditsTotal != null ? ` · est.: ${formatCredits(data.totals.creditsEstimated)}` : null}
              </p>
            </div>
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card className="p-6 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-foreground">Trend ({data.range.bucket === 'day' ? 'Tag' : 'Monat'})</p>
                <p className="text-xs text-muted-foreground">Users w/ costs: {formatNumber(data.totals.usersWithCosts)}</p>
              </div>
              {bucketRows.length === 0 ? (
                <p className="text-sm text-muted-foreground">Keine Daten.</p>
              ) : (
                <div className="space-y-2">
                  {bucketRows.map((m) => (
                    <BucketBar key={m.key} row={m} maxCost={maxBucketCost} />
                  ))}
                </div>
              )}
            </Card>

            <Card className="p-6 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-foreground">Top Users</p>
                <p className="text-xs text-muted-foreground">Top {Math.min(25, data.topUsers.length)}</p>
              </div>
              {data.topUsers.length === 0 ? (
                <p className="text-sm text-muted-foreground">Keine Daten.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>#</TableHead>
                      <TableHead>User</TableHead>
                      <TableHead className="text-right">Cost</TableHead>
                      <TableHead className="text-right">Ops</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.topUsers.slice(0, 12).map((u, idx) => (
                      <TableRow key={u.uid}>
                        <TableCell className="text-xs text-muted-foreground">{idx + 1}</TableCell>
                        <TableCell className="text-xs">
                          <div className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-foreground truncate">{rowLabel(u)}</p>
                              <p className="text-[11px] text-muted-foreground truncate">{u.uid}</p>
                            </div>
                            <Button asChild variant="ghost" size="sm" className="h-8">
                              <Link href={`/admin/users/${encodeURIComponent(u.uid)}`}>Details</Link>
                            </Button>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs text-right text-foreground">{formatUsd(u.costUsd)}</TableCell>
                        <TableCell className="text-xs text-right text-muted-foreground">{formatNumber(u.count)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Card>
          </div>

          {data.scan?.enabled ? (
            <div className="space-y-4">
              <Card className="p-6 space-y-2">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm font-medium text-foreground">Breakdown (Scan)</p>
                  <p className="text-xs text-muted-foreground">{scanNote}</p>
                </div>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 pt-2">
                  <div className="rounded-lg border bg-background p-4">
                    <p className="text-xs text-muted-foreground">Scan Cost</p>
                    <p className="text-lg font-semibold text-foreground mt-1">{formatUsd(data.scan.totals.costUsd)}</p>
                  </div>
                  <div className="rounded-lg border bg-background p-4">
                    <p className="text-xs text-muted-foreground">Scan Credits</p>
                    <p className="text-lg font-semibold text-foreground mt-1">{formatCredits(data.scan.totals.credits)}</p>
                  </div>
                  <div className="rounded-lg border bg-background p-4">
                    <p className="text-xs text-muted-foreground">Scanned Ops</p>
                    <p className="text-lg font-semibold text-foreground mt-1">{formatNumber(data.scan.operationsScanned)}</p>
                  </div>
                  <div className="rounded-lg border bg-background p-4">
                    <p className="text-xs text-muted-foreground">Scan Complete</p>
                    <p className="text-lg font-semibold text-foreground mt-1">{data.scan.complete ? 'Yes' : 'No'}</p>
                  </div>
                </div>
              </Card>

              <div className="grid lg:grid-cols-2 gap-4">
                <BreakdownBadges title="Operation Types" rows={data.scan.byOperationType || []} labelKey="operationType" />
                <BreakdownBadges title="Models" rows={data.scan.byModel || []} labelKey="model" />
              </div>
              <div className="grid lg:grid-cols-2 gap-4">
                <BreakdownBadges title="Status" rows={data.scan.byStatus || []} labelKey="status" />
                <BreakdownBadges title="Key Source" rows={data.scan.byKeySource || []} labelKey="keySource" />
              </div>
            </div>
          ) : null}

          <OperationsTable
            preset={preset === 'all' ? 'all' : 'custom'}
            startKey={startKey}
            endKey={endKey}
            onMissingIndex={setOpsMissingIndex}
          />
        </>
      )}
    </div>
  );
}
