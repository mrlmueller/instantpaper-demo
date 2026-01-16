'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

type AdminBillingBalance = {
  totalCredits: number;
  subscriptionCredits: number;
  subscriptionExpiresAt: string | null;
  topupCredits: number;
  reservedCredits: number;
  availableCredits: number;
  isNegative: boolean;
};

type OperationEstimate = {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  costUsd?: number;
  spendRate?: number;
  credits?: number;
} & Record<string, unknown>;

type OperationTokens = {
  inputTokens?: number;
  cachedInputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
} & Record<string, unknown>;

type OperationCosts = {
  totalCostUsd?: number;
} & Record<string, unknown>;

type OperationReservation = {
  reservedCredits?: number;
  reservedAt?: string | null;
  releasedAt?: string | null;
  releaseReason?: string | null;
} & Record<string, unknown>;

type OpenAIOperationRow = {
  id: string;
  operationId: string;
  timestamp: string | null;
  runningAt?: string | null;
  status: string;
  errorMessage: string | null;
  operationType: string;
  operationDetails?: unknown;
  userActionId?: string | null;
  model?: string | null;
  keySource?: string | null;
  estimate?: OperationEstimate;
  tokens?: OperationTokens;
  costs?: OperationCosts;
  reservation?: OperationReservation | null;
  actualCredits?: number | null;
};

type OpenAIOperationsResponse = {
  operations?: OpenAIOperationRow[];
  nextCursor?: string | null;
  error?: string;
};

type ReservedCreditsMode = 'delta' | 'set';

function formatCredits(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '0.00';
  return n.toFixed(2);
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

function statusBadgeClass(status: string): string {
  const s = String(status || '').toLowerCase();
  if (s === 'success') return 'bg-primary text-primary-foreground border-transparent';
  if (s === 'running' || s === 'reserved') return 'bg-amber-500 text-white border-transparent';
  if (s === 'skipped') return 'bg-muted text-foreground border-transparent';
  if (s === 'blocked') return 'bg-destructive text-white border-transparent';
  if (s === 'error') return 'bg-destructive text-white border-transparent';
  return 'bg-muted text-foreground border-transparent';
}

function formatUsd(value: number | null | undefined): string | null {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n) || n <= 0) return null;
  return `$${n.toFixed(6)}`;
}

export function AdminUserOpenAIOperationsPanel({
  uid,
  balance,
  refreshNonce,
  onRefresh,
}: {
  uid: string;
  balance: AdminBillingBalance;
  refreshNonce?: number;
  onRefresh?: () => void;
}) {
  const [operations, setOperations] = useState<OpenAIOperationRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);

  const [reservedMode, setReservedMode] = useState<ReservedCreditsMode>('delta');
  const [reservedAmount, setReservedAmount] = useState('');
  const [reservedNote, setReservedNote] = useState('');
  const [savingReserved, setSavingReserved] = useState(false);

  const headline = useMemo(() => {
    return {
      total: formatCredits(balance?.totalCredits ?? 0),
      available: formatCredits(balance?.availableCredits ?? 0),
      reserved: formatCredits(balance?.reservedCredits ?? 0),
      subscription: formatCredits(balance?.subscriptionCredits ?? 0),
      topup: formatCredits(balance?.topupCredits ?? 0),
      expires: balance?.subscriptionExpiresAt ? formatIso(balance.subscriptionExpiresAt) : null,
    };
  }, [balance]);

  const loadOps = async (cursor: string | null) => {
    const qs = new URLSearchParams();
    qs.set('limit', '30');
    if (cursor) qs.set('cursor', cursor);
    const url = `/api/admin/users/${encodeURIComponent(uid)}/openai/operations?${qs.toString()}`;

    const res = await fetch(url, { method: 'GET', cache: 'no-store' });
    const data = (await res.json().catch(() => ({}))) as OpenAIOperationsResponse;
    if (!res.ok) throw new Error(data?.error || 'OpenAI Operationen konnten nicht geladen werden.');

    const ops = Array.isArray(data.operations) ? data.operations : [];
    const next = typeof data.nextCursor === 'string' ? data.nextCursor : null;
    return { operations: ops, nextCursor: next };
  };

  const reload = async () => {
    setLoading(true);
    try {
      const { operations, nextCursor } = await loadOps(null);
      setOperations(operations);
      setNextCursor(nextCursor);
    } catch (err: any) {
      toast.error('OpenAI', { description: err?.message || 'OpenAI Operationen konnten nicht geladen werden.' });
      setOperations([]);
      setNextCursor(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setOperations([]);
    setNextCursor(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, refreshNonce]);

  const handleAdjustReserved = async () => {
    if (savingReserved) return;
    const amountNum = Number(reservedAmount);
    if (!Number.isFinite(amountNum)) {
      toast.error('Reserved Credits', { description: 'Bitte eine gültige Zahl eingeben.' });
      return;
    }

    setSavingReserved(true);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/billing/reserved-credits`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: reservedMode, amount: amountNum, note: reservedNote || null }),
      });
      const data = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) throw new Error(data?.error || 'Konnte reservedCredits nicht anpassen.');

      toast.success('Reserved Credits angepasst');
      setReservedAmount('');
      setReservedNote('');
      onRefresh?.();
      await reload();
    } catch (err: any) {
      toast.error('Reserved Credits', { description: err?.message || 'Konnte reservedCredits nicht anpassen.' });
    } finally {
      setSavingReserved(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-lg border p-6">
        <h2 className="text-sm font-semibold text-foreground">Balance</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Credits</p>
            <p className="text-2xl font-semibold text-foreground mt-1">{headline.total} Credits</p>
            <div className="mt-2 text-sm text-muted-foreground grid gap-1">
              <div>
                Available: <span className="text-foreground">{headline.available}</span>
              </div>
              <div>
                Reserved: <span className="text-foreground">{headline.reserved}</span>
              </div>
              <div>
                Abo: <span className="text-foreground">{headline.subscription}</span>
              </div>
              <div>
                Top-up: <span className="text-foreground">{headline.topup}</span>
              </div>
              {headline.expires ? <div>Abo bis: {headline.expires}</div> : null}
            </div>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Reserved Credits</p>
            <p className="text-lg font-medium text-foreground mt-1">Manuelle Korrektur</p>
            <p className="text-xs text-muted-foreground mt-1">
              Für den Fall, dass ein Crash reservedCredits hängen lässt.
            </p>
            <div className="mt-4 grid gap-3">
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={reservedMode === 'delta' ? 'default' : 'outline'}
                  onClick={() => setReservedMode('delta')}
                  disabled={savingReserved}
                >
                  Delta
                </Button>
                <Button
                  type="button"
                  variant={reservedMode === 'set' ? 'default' : 'outline'}
                  onClick={() => setReservedMode('set')}
                  disabled={savingReserved}
                >
                  Set
                </Button>
              </div>
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="reserved-amount">
                  Betrag ({reservedMode})
                </label>
                <Input
                  id="reserved-amount"
                  type="number"
                  step="0.01"
                  value={reservedAmount}
                  onChange={(e) => setReservedAmount(e.target.value)}
                  placeholder={reservedMode === 'delta' ? '-10 oder +10' : 'z.B. 0'}
                  disabled={savingReserved}
                />
              </div>
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="reserved-note">
                  Notiz (optional)
                </label>
                <Textarea
                  id="reserved-note"
                  value={reservedNote}
                  onChange={(e) => setReservedNote(e.target.value)}
                  placeholder="z.B. stuck reservations nach Crash"
                  disabled={savingReserved}
                />
              </div>
              <Button type="button" onClick={handleAdjustReserved} disabled={savingReserved}>
                {savingReserved ? 'Speichern…' : 'Anwenden'}
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border p-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">OpenAI Operationen</h2>
            <p className="text-xs text-muted-foreground mt-1">Estimate vs Actual (Tokens + Credits)</p>
          </div>
          <Button variant="outline" onClick={reload} disabled={loading}>
            Reload
          </Button>
        </div>

        {loading ? (
          <div className="mt-4 space-y-3">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : operations.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">Keine Operationen gefunden.</p>
        ) : (
          <div className="mt-4 divide-y">
            {operations.map((op) => {
              const status = String(op.status || 'unknown');
              const est = op.estimate || {};
              const tok = op.tokens || {};
              const costs = op.costs || {};
              const estCredits = Number(est.credits ?? 0);
              const actCredits = op.actualCredits ?? null;
              const costUsd = formatUsd(Number(costs.totalCostUsd ?? 0));

              return (
                <div key={op.operationId || op.id} className="py-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge className={cn('rounded-md px-2 py-0.5 text-[11px] font-semibold', statusBadgeClass(status))}>
                          {status}
                        </Badge>
                        <p className="text-sm font-medium text-foreground truncate max-w-[520px]">
                          {op.operationType || '-'}
                        </p>
                        {op.model ? (
                          <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-[11px] font-semibold">
                            {op.model}
                          </Badge>
                        ) : null}
                        {op.keySource ? (
                          <span className="text-[11px] text-muted-foreground uppercase">{op.keySource}</span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {formatIso(op.timestamp || null)} • opId: <span className="font-mono">{op.operationId}</span>
                      </p>
                      {op.errorMessage ? (
                        <p className="mt-2 text-xs text-destructive">{op.errorMessage}</p>
                      ) : null}
                    </div>

                    <div className="shrink-0 text-right text-xs text-muted-foreground">
                      <div>
                        Est: <span className="text-foreground">{formatCredits(estCredits)}</span> cr
                      </div>
                      <div>
                        Act:{' '}
                        <span className="text-foreground">
                          {actCredits == null ? '-' : formatCredits(Number(actCredits))}
                        </span>{' '}
                        cr
                      </div>
                      <div>{costUsd ? `USD: ${costUsd}` : null}</div>
                    </div>
                  </div>

                  <div className="mt-3 grid gap-2 md:grid-cols-2 text-xs">
                    <div className="rounded-md border p-3">
                      <p className="text-xs text-muted-foreground">Tokens</p>
                      <div className="mt-1 text-muted-foreground">
                        <div>
                          Est in/out:{' '}
                          <span className="text-foreground">
                            {Number(est.inputTokens ?? 0)}/{Number(est.outputTokens ?? 0)}
                          </span>
                        </div>
                        <div>
                          Act in/out:{' '}
                          <span className="text-foreground">
                            {Number(tok.inputTokens ?? 0)}/{Number(tok.outputTokens ?? 0)}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="rounded-md border p-3">
                      <p className="text-xs text-muted-foreground">Reservation</p>
                      <div className="mt-1 text-muted-foreground">
                        <div>
                          Reserved:{' '}
                          <span className="text-foreground">
                            {formatCredits(Number(op.reservation?.reservedCredits ?? 0))}
                          </span>
                        </div>
                        <div>ReservedAt: {formatIso(op.reservation?.reservedAt ?? null)}</div>
                        <div>ReleasedAt: {formatIso(op.reservation?.releasedAt ?? null)}</div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {nextCursor ? (
          <div className="mt-4">
            <Button
              variant="outline"
              onClick={() => {
                if (!nextCursor || moreLoading) return;
                setMoreLoading(true);
                loadOps(nextCursor)
                  .then(({ operations, nextCursor }) => {
                    setOperations((prev) => [...prev, ...operations]);
                    setNextCursor(nextCursor);
                  })
                  .catch((err: any) => {
                    toast.error('OpenAI', { description: err?.message || 'OpenAI Operationen konnten nicht geladen werden.' });
                  })
                  .finally(() => setMoreLoading(false));
              }}
              disabled={moreLoading}
            >
              {moreLoading ? 'Laden…' : 'Mehr laden'}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

